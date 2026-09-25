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
| `data-engineer-ferry` (ferry) | ETL + dbt | `etl/`, `fixtures/`, `demo_data/`, `dbt/` | `data-engineer-py`, `dax-sql-formatter` | own `tools` list; read-only Supabase `list_tables`, `list_migrations`, `search_docs`; no `execute_sql`, no `apply_migration` |
| `db-chef` (chef) | Warehouse (schema `qbo`) | `supabase/` (migrations: DDL / init code, roles, grants; validation SQL) | `db-schema-architect`, `pg-sql-dev`, `dax-sql-formatter` | own `tools` list; read-only Supabase catalog and advisor tools; no `execute_sql`, no `apply_migration` |
| `bip` | PBI model & report + PBI Service | `PNL/`, `.docs/model/`, workspace items | `pbip-editor`, `dax-sql-formatter` | inherits every tool except Vercel and Supabase `apply_migration` / `deploy_edge_function` |
| — | Web report | `web/` | — | no agent for now (USER) |

## Decision — rules

- **dbt belongs to ferry:** every `stg_*` and `vw_*` model, the incremental fills of the migration-owned `dim_*` / `fact_*`, the dbt tests (spec §3.1: one per `DetailType`), `dbt_project.yml` and `profiles.yml`. ADR-0002 still binds: views only, `full_refresh: false`, no DDL on tables.
- **Table changes are migrations:** when a dbt model needs a table change, ferry proposes it, chef writes the migration file, and the main session applies it after USER approval (ADR-0003).
- **Shared metrics:** the serve views are dbt models, so a metric shown by both Power BI and the web report is owned by the ETL + dbt lane (the `vw_*` column) and documented in `.docs/model/`. bip and the web report only present it.
- **Routing and logs:** the main session routes single-lane work to the lane's agent, runs cross-lane work itself, and writes `.log/` (coms, daily, plan). A delegated agent writes only its own memory (`.claude/agent-memory/<agent>/`) and hands back a summary.
- **Remote writes stay with the main session and the USER:** no sub-agent has `apply_migration`; only bip keeps `execute_sql`, which runs read-only statements only (`CLAUDE.md`).
- **Memory IDs:** `CAND-NNN` and `AP-NNN` belong to the project anti-pattern catalogue. chef's memory candidates use `SCAND-NNN`, ferry's `PCAND-NNN`.
- **Addressing:** invoke an agent by its file name (`@data-engineer-ferry`, `@db-chef`, `@bip`); the short names are for conversation only.

## ferry alignment (resolved, USER 2026-09-25)

- SQL style: `dax-sql-formatter` replaces `sql-style-formatter`.
- `execute_sql` dropped (it connects as `postgres` and can write); ferry checks data through dbt or Python as `qbo_etl`.
- Tool names that don't exist on this project's servers removed: `mcp__supabase__get_logs`, `mcp__microsoft-learn__*`.
- Data processing: DuckDB first, pandas as fallback, no Polars; money stays `Decimal` / `DECIMAL(15,2)`.
- Environment: `etl/.venv` + pinned `etl/requirements.txt` (no `uv` / `pyproject.toml`). Drivers: psycopg 3.3.6 for the ETL (passed the Smart App Control test), psycopg2 2.9.10 for dbt.
- Orchestration: no Airflow or managed ingestion; the daily run is a Windows Task Scheduler job (ADR-0004).
- Memory candidates: `PCAND-NNN`.

## Consequences

- The `CLAUDE.md` lane table gets an Agent column; `dbt/` moves from the Warehouse row to the ETL + dbt row, and the shared-metric owner moves with it.
- F-05 spans two lanes: migrations M1–M5 → chef; the spec §3 dbt models → ferry.
- Role `qbo_etl` (ADR-0003) already serves both halves of ferry's lane (`qbo_sync` and dbt), so no role changes.
- A web report agent, once ADR-0005 is decided, amends this ADR.
