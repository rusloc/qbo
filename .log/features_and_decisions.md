# Features & decisions — QBO P&L

> `idea → decisions → features` read-through of the ADR ledger (`.docs/ADR/`). Updated in lockstep with `.log/daily/`.
> Feature states: `planned` → `in progress` → `implemented`.

## Idea: QBO → Power BI P&L template (spec `.docs/qbo-pnl-project-spec.md`)

### Decisions
- 2026-09-25 #decision Warehouse = Supabase Postgres; Azure SQL path dropped — ADR-0001 (accepted)
- 2026-09-25 #decision Two consumers of the serve layer: Power BI model + React online report (spec amendment pending)
- 2026-09-25 #decision AI tooling = pbi-fabric-agent-kit 2026-09-25 (skills, `powerbi-modeling` MCP, report CLIs)
- 2026-09-25 #decision Supabase project `vosk.dev` is shared with the USER's other backends; QBO lives in its own schema; rule "one Supabase project per client" dropped — ADR-0008 (accepted)
- 2026-09-25 #decision dbt-core + dbt-postgres for all transformations; DDL / init code stays in migrations — ADR-0002 (accepted)
- 2026-09-25 #decision Schema `qbo` holds every QBO object — ADR-0003 (accepted: schema; roles `qbo_etl` / `qbo_reader`; no Data API exposure; migrations applied via MCP `apply_migration` with USER approval and verified on `vosk.dev`)
- 2026-09-25 #decision Refresh token in Supabase Vault (primary; another store acceptable if Vault falls short) — ADR-0007 (accepted)
- 2026-09-25 #decision Git commit messages never reference Anthropic, Claude or Claude Code (CLAUDE.md, USER)
- 2026-09-25 #decision Sub-agents: `bip` = PBI model & report + PBI Service; `db-chef` = schema `qbo` (`supabase/` migrations, validation SQL); dbt ownership decided when the data-engineer agent lands; no web report agent for now. Delegated agents don't write `.log/` (main session logs); chef's memory candidates use `SCAND-NNN` (project keeps `CAND-NNN` / `AP-NNN`) — roster ADR pending (ADR-0009)
- 2026-09-25 #decision `data-engineer-ferry` joins as the ETL + dbt agent and owns all dbt work (`dbt/`: `stg_*` / `vw_*` models, fills of migration-owned `dim_*` / `fact_*`, dbt tests) plus `etl/`, `fixtures/`, `demo_data/`; `db-chef` keeps the migrations; shared PBI / web metrics (serve-view columns) move to the ETL + dbt lane — ADR-0009 (accepted)

### Open ADR candidates
- ADR-0004 — where and how `qbo_sync cdc` runs daily
- ADR-0005 — React report: plotting library, build tool, hosting
- ADR-0006 — Power BI Service: refresh path (cloud connection vs gateway) and deploy tool

### Features
| ID | Feature | Spec | State |
|---|---|---|---|
| F-01 | Sandbox company + JSON fixtures per entity and `DetailType` | §4 P0 Track A | planned |
| F-02 | Synthetic demo dataset (`generate_synthetic.py`, 24 months) | §4 P0 Track C | planned |
| F-03 | Sandbox seeding (`seed_sandbox.py`) | §4 P0 Track B | planned |
| F-04 | Extractor `qbo_sync` (auth, backfill, cdc, status) | §4 P1 | planned |
| F-05 | Warehouse DDL + transforms raw → stg → mart → serve | §2, §3, §4 P2 | planned |
| F-06 | Validation suite V1–V3 | §5, §4 P3 | planned |
| F-07 | Power BI single-page P&L (PBIP → .pbit + demo .pbix) | §6, §7, §4 P4 | planned |
| F-08 | React online report | USER 2026-09-25 | planned (scope to be specified) |
