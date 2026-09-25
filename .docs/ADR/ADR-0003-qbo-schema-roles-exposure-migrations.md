# ADR-0003 — Schema `qbo`, DB roles, Data API exposure, migration apply path

- **Status:** schema `qbo` **Accepted** (USER, 2026-09-25) · roles, exposure and migration apply path **Proposed** (awaiting USER)
- **Related:** ADR-0001 (warehouse), ADR-0002 (dbt vs migrations), ADR-0007 (token vault), ADR-0008 (shared project)

## Context

ADR-0008 puts QBO in its own namespace inside the shared Supabase project `vosk.dev`.
Read-only check on 2026-09-25: no `qbo` schema or roles exist yet, and the database has no database-wide default privileges, so a new schema grants nothing to `PUBLIC`, `anon` or `authenticated`.
The shared migration history already holds the other app's 8 migrations, so `supabase db push` from this repo cannot be used on `vosk.dev` (ADR-0008).

## Decision — accepted

- **One schema, `qbo`, holds every QBO object.** Spec §2 names stay unchanged and are schema-qualified (`qbo.raw_entity`, `qbo.vw_fact_gl`).
- Power BI navigates to schema `qbo` as a constant; its parameters stay `Server`, `Database`, `FY_START` (spec §4).

## Decision — proposed

**Roles** (created `nologin` by a migration; the USER enables login and sets passwords outside the repo; clients connect through the session pooler as `<role>.<project-ref>`):

| Role | Used by | Rights |
|---|---|---|
| `qbo_etl` | `qbo_sync` + dbt | `usage` + `create` on `qbo` (dbt views); `select, insert` on `raw_entity` (raw stays insert-only); `select, insert, update` on `sync_state` and `dim_*`; full DML on `fact_*`; `select, insert` on `qa_reports_snapshot` |
| `qbo_reader` | Power BI | `usage` on `qbo`; `select` on `vw_*` only, granted by dbt (`grants` config) |

- The `postgres` role (the migration runner) owns the tables, so `qbo_etl` cannot alter or drop them.

**Exposure:**
- `qbo` stays out of the Data API exposed schemas, and nothing is granted to `anon` or `authenticated`.
- No RLS on `qbo` tables: they are unreachable from the API, and RLS without policies would lock out `qbo_etl`.
- `vw_*` are ordinary (owner-rights) views, so `qbo_reader` needs no grants on the base tables.
- The React report's access path (a separate exposed schema with `security_invoker` views, or RPC functions) is decided with ADR-0005.

**Migration apply path:**
- Migration files live in `supabase/migrations/`, named per the CLI convention `<yyyymmddhhmmss>_qbo_<name>.sql`. They are the source of truth.
- Each file is applied to `vosk.dev` through the Supabase MCP `apply_migration` under the same name, one file per call, after the USER approves that call.
- `supabase db push` never runs against `vosk.dev`.
- Drift check: compare the `qbo_*` names in `list_migrations` with the folder.
- Fresh-DB gate: apply the folder in order to a disposable `supabase/postgres` container in CI.
- This needs the MCP with writes enabled, which replaces the earlier `read_only=true` suggestion. Guards:
  - a Claude Code `ask` rule on `mcp__supabase__apply_migration`;
  - a CLAUDE.md rule: `execute_sql` runs read-only statements only; any DDL or DML goes through a migration.

## Consequences

- The Supabase performance advisor will show INFO notices: `qa_reports_snapshot` has no primary key (as in the spec), and the `fact_gl` foreign keys are unindexed. Both are accepted at v1 volume (spec §8: 3K transactions).
- The fresh-DB gate needs Supabase's Postgres image, not plain Postgres (Vault functions, ADR-0007).
- The CLAUDE.md line "Exposure (proposed — ADR-0003)" is rewritten to match; the web path moves to ADR-0005.
