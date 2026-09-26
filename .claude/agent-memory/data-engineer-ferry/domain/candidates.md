<!-- next-id: PCAND-004 -->

# Candidates

### PCAND-001 · ruff 0.16.9 default rule set flags Decimal("0") (FURB157) and naive datetime (DTZ001) · first seen 2026-09-26
**Where:** etl/ ruff check with no config file
**Why interesting:** defaults are wider than the classic E4/E7/E9/F set; `Decimal("7500")` -> `Decimal(7500)` autofix is value- and exponent-identical (verified by byte-identical demo files), but `Decimal("0.00")` is correctly left alone.
**Watch for:** autofix on non-integer strings; ferry-B / new code tripping the same rules.
**Tags:** ruff, lint, decimal, datetime
**Promote-to:** tool-quirks.md (TOOL)
**Expires:** 2026-12-25

### PCAND-002 · dbt-postgres view rebuild drops dependent stg views (drop ... cascade) · first seen 2026-09-26
**Where:** stg_entity_latest <- stg_account / stg_item / stg_txn_line (views on views)
**Why interesting:** a partial `run_dbt.py build -s stg_entity_latest` would drop the downstream stg views and not recreate them; vw_* are safe (they read tables only). Not verified on the DB yet.
**Watch for:** "relation qbo.stg_txn_line does not exist" after a selective run.
**Tags:** dbt, postgres, view, cascade, selection
**Promote-to:** tool-quirks.md (TOOL)
**Expires:** 2026-12-25

### PCAND-003 · QBO name-list queries return Active = true only · first seen 2026-09-26
**Where:** ferry-B finding (etl/qbo_sync/entities.py): backfill adds `where Active in (true, false)`
**Why interesting:** inactive accounts / customers with history would otherwise orphan fact rows (gate P2 fails).
**Watch for:** orphan account_key / relationships test failures after a real backfill.
**Tags:** qbo, active, name-list, backfill, orphans
**Promote-to:** tool-quirks.md (SRC)
**Expires:** 2026-12-25
