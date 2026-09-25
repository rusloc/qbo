# ADR-0009 — Sub-agent roster: one agent per lane; dbt belongs to the data engineer

- **Status:** Accepted (USER, 2026-09-25)
- **Supersedes:** `CLAUDE.md` "Single-agent project for now"
- **Related:** ADR-0002 (dbt vs migrations), ADR-0003 (schema `qbo`, roles, apply path), ADR-0004 (ETL runtime, open), ADR-0005 (web stack, open)

## Context

`CLAUDE.md` ran the project with one agent and said that once sub-agents are introduced, each lane becomes one agent, ADR first.
On 2026-09-25 the USER added three sub-agents in `.claude/agents/`: `bip`, `db-chef` and `data-engineer-ferry`.
ADR-0002 splits the warehouse work in two: migrations own the tables; dbt builds the views and fills the tables. The USER gave dbt to the data engineer, not to the schema architect.

## Decision — roster

| Agent (short name) | Lane | Owns (paths) | Preloaded skills | Tool limits |
|---|---|---|---|---|
| `data-engineer-ferry` (ferry) | ETL + dbt | `etl/`, `fixtures/`, `demo_data/`, `dbt/` | `data-engineer-py`, `sql-style-formatter` | own `tools` list; Supabase MCP `execute_sql`, `list_tables`, `list_migrations`, `search_docs` |
| `db-chef` (chef) | Warehouse (schema `qbo`) | `supabase/` (migrations: DDL / init code, roles, grants; validation SQL) | `db-schema-architect`, `pg-sql-dev`, `dax-sql-formatter` | own `tools` list; read-only Supabase catalog and advisor tools; no `execute_sql`, no `apply_migration` |
| `bip` | PBI model & report + PBI Service | `PNL/`, `.docs/model/`, workspace items | `pbip-editor`, `dax-sql-formatter` | inherits every tool except Vercel and Supabase `apply_migration` / `deploy_edge_function` |
| — | Web report | `web/` | — | no agent for now (USER) |

## Decision — rules

- **dbt belongs to ferry:** every `stg_*` and `vw_*` model, the incremental fills of the migration-owned `dim_*` / `fact_*`, the dbt tests (spec §3.1: one per `DetailType`), `dbt_project.yml` and `profiles.yml`. ADR-0002 still binds: views only, `full_refresh: false`, no DDL on tables.
- **Table changes are migrations:** when a dbt model needs a table change, ferry proposes it, chef writes the migration file, and the main session applies it after USER approval (ADR-0003).
- **Shared metrics:** the serve views are dbt models, so a metric shown by both Power BI and the web report is owned by the ETL + dbt lane (the `vw_*` column) and documented in `.docs/model/`. bip and the web report only present it.
- **Routing and logs:** the main session routes single-lane work to the lane's agent, runs cross-lane work itself, and writes `.log/` (coms, daily, plan). A delegated agent writes only its own memory (`.claude/agent-memory/<agent>/`) and hands back a summary.
- **Remote writes stay with the main session and the USER:** no sub-agent has `apply_migration`; `execute_sql` runs read-only statements only (`CLAUDE.md`).
- **Memory IDs:** `CAND-NNN` and `AP-NNN` belong to the project anti-pattern catalogue. chef's memory candidates use `SCAND-NNN`.
- **Addressing:** invoke an agent by its file name (`@data-engineer-ferry`, `@db-chef`, `@bip`); the short names are for conversation only.

## Open (ferry)

- It preloads `sql-style-formatter`; `CLAUDE.md` mandates `dax-sql-formatter` for every SQL statement.
- `execute_sql` connects as `postgres` and can write; read-only is a rule, not a guard. Keep it or drop it.
- Tool names that don't exist on this project's servers: `mcp__supabase__get_logs`, `mcp__microsoft-learn__*`.
- Generic defaults that clash with `CLAUDE.md`: Polars / pandas vs `Decimal` money; `uv` / `pyproject.toml` / psycopg 3 vs `etl/.venv` + `requirements.txt` + psycopg2 2.9.10; Airflow / managed ingestion vs the open ADR-0004; memory candidates `CAND-NNN`.

## Consequences

- The `CLAUDE.md` lane table gets an Agent column; `dbt/` moves from the Warehouse row to the ETL + dbt row, and the shared-metric owner moves with it.
- F-05 spans two lanes: migrations M1–M5 → chef; the spec §3 dbt models → ferry.
- Role `qbo_etl` (ADR-0003) already serves both halves of ferry's lane (`qbo_sync` and dbt), so no role changes.
- A web report agent, once ADR-0005 is decided, amends this ADR.
