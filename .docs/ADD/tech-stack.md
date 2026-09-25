# Tech stack + rationale — QBO P&L

> Status legend: **fixed** = set by the spec · **decided** = accepted ADR · **open** = ADR candidate, not decided. Do not implement against an open row without the ADR.

| Layer | Choice | Status | Source / ADR |
|---|---|---|---|
| Source | QuickBooks Online Accounting API v3, `minorversion=75`, OAuth 2.0 (`com.intuit.quickbooks.accounting`) | fixed | spec §1 |
| Extract + load | Python 3.12 CLI `qbo_sync` (`auth`, `backfill`, `cdc`, `status`) | fixed | spec §0, §4 P1 |
| Demo data | `generate_synthetic.py` → QBO-shaped JSON into `raw_entity` (not CSV) + `seed_sandbox.py` (QBO sandbox) | decided | spec §4 P0; JSON: USER 2026-09-25 (CLAUDE.md spec delta 3) |
| Local data processing + drivers | DuckDB 1.5.5 first, pandas fallback (not installed), no Polars; psycopg 3.3.6 (ETL), psycopg2 2.9.10 (dbt); env `etl/.venv` + pinned `etl/requirements.txt`; native wheels pass a Smart App Control test before pinning | decided | USER 2026-09-25; ADR-0009 |
| Warehouse | Supabase (managed PostgreSQL), project `vosk.dev`, shared with the USER's other backends; QBO in its own schema | decided | ADR-0001, ADR-0008; project: USER 2026-09-25 |
| Schema migrations | files in `supabase/migrations/` (CLI naming, `qbo_` names) = all DDL / init code; applied via Supabase MCP `apply_migration` after USER approval; never `supabase db push` on `vosk.dev` | decided | ADR-0001, ADR-0002, ADR-0003, ADR-0008 |
| Transforms raw → stg → mart → serve | dbt-core + dbt-postgres: `stg_*` / `vw_*` views; fills migration-owned `dim_*` / `fact_*` (incremental merge / delete+insert) | decided | ADR-0002 |
| Schema layout + Data API exposure + DB roles | one schema `qbo` (all layers); roles `qbo_etl` (ETL + dbt) and `qbo_reader` (Power BI, `vw_*` only); `qbo` not exposed through the Data API; web path with ADR-0005 | decided | ADR-0003 |
| ETL runtime + schedule | `qbo_sync cdc` daily via Windows Task Scheduler on the USER's PC (catch-up after missed runs, single instance); `backfill` / `auth` by hand | decided | ADR-0004 |
| Web report | React + TypeScript; plotting library, build tool, hosting | open | ADR-0005 |
| Power BI | Desktop PBIP (TMDL + PBIR), Import mode, PostgreSQL connector | fixed | spec §4 P4, §7 |
| Power BI Service | refresh path (cloud connection vs on-premises gateway), deploy tool (deployment pipelines / `fab`) | open | ADR-0006 |
| OAuth token vault | Supabase Vault secret `qbo_refresh_token` behind two `security definer` functions (USER: Vault is primary; another store is acceptable if Vault falls short) | decided | ADR-0007 |
| Tests | pytest (+ fixtures per `DetailType`), SQL validation V1–V3; web: Vitest | fixed (web: proposed) | spec §3.1, §5, §8 |
| AI tooling | Claude Code + pbi-fabric-agent-kit 2026-09-25 (skills, `powerbi-modeling` MCP, report CLIs) | decided | USER 2026-09-25 |
| AI sub-agents | one per lane: `data-engineer-ferry` (ETL + all dbt), `db-chef` (schema `qbo` migrations), `bip` (PBI model, report, Service); web report: none yet | decided | ADR-0009 |
