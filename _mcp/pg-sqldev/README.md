# pg-sqldev

Local, read-only MCP server that gives a coding agent the PostgreSQL catalog facts it needs to write
efficient analytical SQL, while touching the database as little as possible.
Design and build board: `.log/plan/2026-09-18-mcp-pg-sqldev.html`, `.log/plan/2026-09-18.md`.

Status: **increment 1 built and tested offline. Not yet run against the real database.**

| Tool | Returns | DB cost |
|---|---|---|
| `connection_info` | version, Citus yes/no, role, guards in force, schemas in scope, cache and query counters | 1 catalog query, cached (+1 on a Citus cluster) |
| `schema_overview` | relations by kind with estimated rows / size, last analyze, comment; families by name prefix | 1 catalog query for the whole list, cached; every filter runs in memory |
| `describe_table` | up to 10 relations: columns + planner statistics, keys both directions, indexes + usage, partition / Citus info, view definition | 2 catalog queries per batch, cached |

## Setup, in this order

### 1. Read-only role (decision D1)

On Azure Cosmos DB for PostgreSQL a role is created in the Azure portal (cluster → Roles), not with
`create role`. Create one, for example `bi_sqldev_ro`, then grant as the admin role:

```sql
grant usage on schema public, portal, portal_dev to bi_sqldev_ro;
grant select on all tables in schema public, portal, portal_dev to bi_sqldev_ro;

-- tables created later by the role that runs this statement
alter default privileges in schema public, portal, portal_dev
    grant select on tables to bi_sqldev_ro;
```

`select` is needed even for the catalog-only tools: `pg_stats` shows column statistics only for
columns the role may select. The probe reports how many relations are selectable, so a missed
grant shows up immediately. Without a dedicated role the server still enforces read-only per
transaction, but the role is the stronger barrier.

### 2. Connection file

Copy `.env.example` to `.env` in this folder and fill in `PGUSER` / `PGPASSWORD`.
The server process is the only reader. The coding agent is denied access to `.env*` by
`.claude/settings.json`, which also means it could not re-read `.env.example` after writing it:
**give the template one look before copying it.**

### 3. Probe, once (build step A1)

```bash
node scripts/probe.js
```

At most nine catalog queries, no user table read. Prints a summary for the coms log and writes
`.cache/probe.json`. Its findings decide the open branches: Citus, statistics coverage,
`pg_stat_statements`, privileges, the shape of `public.sql_source`.

### 4. Smoke test = acceptance run (build step A8)

```bash
node test/smoke.js
```

About 40 s. Drives the real server over stdio and checks: scan counters on user tables do not move,
a warm call makes no round trip, no `mcp-pg-sqldev` session is left 30 s after the last call, no
tool call exceeds three catalog queries. Run it **before** registering the server, because a
registered server has sessions of its own. The scan counters are global: on a busy database a
moved counter is reported as INCONCLUSIVE, not as a failure. Report: `.cache/smoke-report.json`.

### 5. Register in Claude Code (build step A9), only after the smoke test passes

Root `.mcp.json`:

```json
{
  "mcpServers": {
    "pg-sqldev": {
      "command": "node",
      "args": ["_mcp/pg-sqldev/src/index.js"]
    }
  }
}
```

Node 24 is installed in `C:\Program Files\nodejs` but was missing from the editor session's PATH on
2026-09-18. Restart VS Code first. If `node` still does not resolve, use
`"command": "C:\\Program Files\\nodejs\\node.exe"`. Then approve the server in Claude Code.

## How it protects the database

- **No raw query path.** Every call runs inside
  `begin transaction read only; set local statement_timeout; set local lock_timeout; ...` and ends
  with `rollback`.
- **Guards are `SET LOCAL`, never session-level.** Through the managed PgBouncer (port 6432) a
  session-level `SET` sticks to a server connection that is later handed to other applications, so a
  session-level read-only default could break someone else's writes. It could also be flipped back
  with `set_config()`. A read-only transaction cannot.
- **Pool of two**, idle sessions close after 25 s, `application_name = mcp-pg-sqldev` so a DBA can
  see them.
- **TLS verification is always on.** `PGSSLROOTCERT` adds a CA bundle. There is no off switch.
- **Catalog first.** No `count(*)`, no size functions: `pg_total_relation_size()` takes a lock and
  would stall behind a materialized view refresh, so sizes are `relpages × block_size` estimates.
- **Statement classifier** (`src/classify.js`) for SQL supplied from outside, used from increment 2:
  single statement, allowlist of `select / with / values / table / explain / show`,
  `explain analyze` only on opt-in, no data-modifying CTE, and a denylist of functions whose effect
  escapes a read-only transaction (`set_config`, `dblink`, advisory locks, `pg_terminate_backend`,
  Citus `run_command_on_workers`, ...), no function that executes SQL passed as a string
  (`query_to_xml`, `ts_stat`, `crosstab`), no `U&` unicode-escaped names. Such statements also go out
  in the extended protocol, which refuses multi-statement strings at the wire level. Hardened after
  an adversarial review on 2026-09-18; every finding is a regression test. What no filter can know
  is what a user-defined or extension function does inside: only role privileges stop that.
- **Cache**: 10 minutes in memory plus `.cache/catalog-snapshot.json`, keyed to the connection
  target. It contains column statistics, and those contain real data values (most common values).
  `.cache/` is ignored by git and must stay so.

## Tests

```bash
npm test
```

Unit tests plus integration tests against PGlite (PostgreSQL compiled to WASM, dev dependency): the
catalog SQL, the guards and the query accounting run on a real engine with a fixture shaped like
this database. `test/library.test.js` runs every mirrored report query of `__DATA/_SRC/_SQL/` through
the classifier, so a rule that would refuse real house SQL fails the build.

What the tests cannot prove: Azure networking, TLS against the real host, real Citus behaviour, real
data volumes. The Citus branch is tested against simulated metadata only.

## Layout

```
src/index.js          bootstrap, stdio transport
src/server.js         MCP server from the registry, error mapping
src/registry.js       tool list
src/config.js         .env loading, validation, redaction
src/db.js             pool, per-transaction guards, accounting
src/classify.js       statement classifier
src/cache.js          TTL cache + disk snapshot
src/capabilities.js   shared server facts, Citus fallback
src/sql.js            loader for src/sql/*.sql (with #if citus variants)
src/sql/*.sql         catalog queries, house SQL style
src/tools/*.js        one file per tool
scripts/probe.js      increment 0
test/*.test.js        node:test units + PGlite integration
test/smoke.js         acceptance run against the real database
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `not configured` | `.env` missing or incomplete. The server reads it once at startup: restart after editing |
| connection timeout | Azure cluster firewall: allow this machine's public IP |
| `28P01` | wrong `PGUSER` / `PGPASSWORD` |
| TLS / certificate error | set `PGSSLROOTCERT` to the CA bundle Azure documents for the service |
| `55P03` lock timeout | a relation is locked, typically a materialized view refresh. `describe_table` retries without view definitions |
| relations or statistics missing | the role lacks `usage` on the schema or `select` on the table |
