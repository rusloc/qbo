# weekly 2026-W39 (2026-09-21 … 2026-09-27)

## Summary
1. Project started 2026-09-25: scaffold, pbi-fabric-agent-kit, repo `rusloc/qbo` (`prod` ← `dev`), setup guide v5 — [daily-2026-09-25](../daily/daily-2026-09-25.md)
2. Architecture settled in 7 accepted ADRs (0001–0004, 0007–0009): Supabase `vosk.dev` shared → schema `qbo`; dbt for transforms, migrations for DDL; refresh token in Vault; Windows Task Scheduler; sub-agent roster
3. Warehouse live: migrations M1–M5 applied to `vosk.dev` and verified; `qbo_etl` / `qbo_reader` can log in; tables still empty
4. Tooling: Python 3.12 only; `etl/.venv` pinned (dbt 1.12.5, psycopg2 2.9.10, psycopg 3.3.6, DuckDB 1.5.5); sub-agents bip / db-chef / ferry aligned with CLAUDE.md
5. Carried to 2026-09-26: `etl/.env`, ETL + dbt build, Power BI access, merge `dev` → `prod`

## Implementations
- Docs: `CLAUDE.md`, spec deltas 1–3, ADR-0001 / 0002 / 0003 / 0004 / 0007 / 0008 / 0009, F-05 warehouse init plan, `tech-stack.md`, setup guide
- Warehouse: schema `qbo`, roles, raw + control tables, 5 dims, `fact_gl` / `fact_budget`, Vault token functions (advisory-lock single-flight)
- Environment: Python 3.12.10, `fab` on 3.12, `etl/.venv`, `dbt/` scaffold (`dbt parse` OK)
- Agents: `bip`, `db-chef`, `data-engineer-ferry` + skill `data-engineer-py`

## Comments — issues, findings, ideas
`vosk.dev` turned out to be a shared project (another app's 8 migrations), so the tenancy rule changed to schema isolation (ADR-0008), and migrations go through MCP `apply_migration` instead of `supabase db push`. Windows Smart App Control blocks new unsigned native wheels (CAND-001), so native packages are pinned to releases that pass a load test. db-chef found silent row-loss risks through nullable or unconstrained filter keys, 3 sightings in the F-05 design (CAND-002). Spec issues still open: budget source for real clients, CI vs live gate steps, `TOTALYTD` vs `FY_START`, `raw_*` vs `raw_entity`. Idea parked: read-only GitHub MCP once CI exists.
