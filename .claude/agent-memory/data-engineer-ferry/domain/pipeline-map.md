# Pipeline map

| Pipeline | Source → Destination | Mover / Transform / Orchestrator | Cadence | Owner | Status | Last touched | Related IDs | Review due |
|---|---|---|---|---|---|---|---|---|
| demo_load (Track C) | etl/generate_synthetic.py → demo_data/*.json → qbo.raw_entity | Python (land_raw, fixed synced_at) / dbt qbo_pnl / manual | on demand | ferry | planned (built, not run on DB) | 2026-09-26 | ISS-002, ISS-006 | 2026-12-25 |
| dbt qbo_pnl | qbo.raw_entity → stg_* → dim_* / fact_* → vw_* (qbo_reader) | dbt-core 1.12.5 / dbt-postgres 1.11.0 via etl/run_dbt.py / manual (Task Scheduler later) | after each load / daily cdc | ferry | planned (parse + offline compile green, not run on DB) | 2026-09-26 | DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, TOOL-001, TOOL-002, SRC-001, ISS-001, ISS-003, ISS-004, ISS-005, ISS-006 | 2026-12-25 |
| qbo_sync | QBO API v3 (sandbox) → qbo.raw_entity, sync_state | Python CLI (ferry-B) / - / Windows Task Scheduler (ADR-0004) | daily cdc, manual backfill | ferry | planned | 2026-09-26 | PCAND-003, ISS-007 | 2026-12-25 |
