# Tech stack + rationale — QBO P&L

> Status legend: **fixed** = set by the spec · **decided** = accepted ADR · **open** = ADR candidate, not decided. Do not implement against an open row without the ADR.

| Layer | Choice | Status | Source / ADR |
|---|---|---|---|
| Source | QuickBooks Online Accounting API v3, `minorversion=75`, OAuth 2.0 (`com.intuit.quickbooks.accounting`) | fixed | spec §1 |
| Extract + load | Python 3.12 CLI `qbo_sync` (`auth`, `backfill`, `cdc`, `status`) | fixed | spec §0, §4 P1 |
| Demo data | `generate_synthetic.py` (CSV) + `seed_sandbox.py` (QBO sandbox) | fixed | spec §4 P0 |
| Warehouse | Supabase (managed PostgreSQL) | decided | ADR-0001 |
| Schema migrations | Supabase CLI (`supabase/migrations/`) | decided | ADR-0001 |
| Transforms raw → stg → mart | plain SQL **or** dbt-core (dbt-postgres) | open | ADR-0002 |
| Schema layout + Data API exposure + DB roles | e.g. `raw` / `stg` / `mart` / `serve` / `qa` schemas; only `serve` exposed; `security_invoker` views; `etl_writer` + `pbi_reader` roles | open | ADR-0003 |
| ETL runtime + schedule | where `qbo_sync cdc` runs daily (GitHub Actions cron / always-on machine / other) | open | ADR-0004 |
| Web report | React + TypeScript; plotting library, build tool, hosting | open | ADR-0005 |
| Power BI | Desktop PBIP (TMDL + PBIR), Import mode, PostgreSQL connector | fixed | spec §4 P4, §7 |
| Power BI Service | refresh path (cloud connection vs on-premises gateway), deploy tool (deployment pipelines / `fab`) | open | ADR-0006 |
| OAuth token vault | where the rotating refresh token is persisted (table with row lock; encryption at rest) | open | ADR-0007 |
| Tests | pytest (+ fixtures per `DetailType`), SQL validation V1–V3; web: Vitest | fixed (web: proposed) | spec §3.1, §5, §8 |
| AI tooling | Claude Code + pbi-fabric-agent-kit 2026-09-25 (skills, `powerbi-modeling` MCP, report CLIs) | decided | USER 2026-09-25 |
