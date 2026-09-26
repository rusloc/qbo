<!-- next-id: DEC-007 -->

# Decisions

### DEC-001 · fact_gl incremental: delete+insert per transaction + source_sync_at watermark · 2026-09-26
**Decision:** unique_key [txn_type, txn_qbo_id] (ADR-0002); batch = transactions whose latest raw synced_at >= max(fact_gl.source_sync_at); `--vars "{full_reload: true}"` reprocesses all.
**Context:** raw is insert-only with synced_at = landing time (qbo_sync now(), demo fixed 2026-09-01); --full-refresh disabled on migration-owned tables.
**Alternatives rejected:** unique_key incl. line_num (a line removed in QBO would survive); full delete+insert every run (no incremental path, spec P2 wants both).
**Consequences:** gl_key churns for re-processed transactions; dim changes (item account remap) need full_reload; deleted txns keep last body lines flagged is_deleted.
**Revisit-when:** a landing path writes synced_at older than the current max (backdated loads are skipped until full_reload).
**Decided-by:** ferry (lane-internal, reported to main session 2026-09-26)
**Related:** ISS-006
**Status:** active

### DEC-002 · fact_budget: full replace in one transaction (append + pre-hook delete) · 2026-09-26
**Decision:** fact_budget model = `incremental_strategy: append` with `pre_hook: delete from {{ this }}`; aggregates active ProfitAndLoss budgets per month / account / class.
**Context:** unique nulls not distinct key with nullable class_key (TOOL-002); deactivated budgets must disappear; ~30 rows per month.
**Alternatives rejected:** merge / delete+insert on the 3-col key (null never matches -> unique violation); delete+insert on budget_month (stale months when a budget is deactivated).
**Consequences:** budget_key churns each run; atomic (hook inside dbt's transaction).
**Revisit-when:** budgets grow past ~100k rows or something references budget_key.
**Decided-by:** ferry (lane-internal, reported 2026-09-26)
**Related:** TOOL-002
**Status:** active

### DEC-003 · Guard ADR-0002 in dbt: exact-type casts + assert_migration_owned macro · 2026-09-26
**Decision:** every mart model casts strings to the table's varchar(n) and calls `assert_migration_owned()` (raises when is_incremental() is false, i.e. table missing or full refresh).
**Context:** qbo_etl has CREATE on schema qbo (for views), so dbt could create a missing mart table; incremental path widens columns (TOOL-001).
**Alternatives rejected:** enforced model contracts (type-name matching vs varchar(n) untestable without a DB this run; revisit).
**Consequences:** unit tests on mart models need `overrides: macros: is_incremental: true`.
**Revisit-when:** contracts are validated against the live DB.
**Decided-by:** ferry (lane-internal, reported 2026-09-26)
**Related:** TOOL-001
**Status:** active

### DEC-004 · Budget source = QBO Budget entity, landed in raw_entity · 2026-09-26
**Decision:** fact_budget is filled from the QBO `Budget` entity (resolves spec issue 3); synthetic generator emits QBO-shaped Budget JSON.
**Context:** USER decision 2026-09-26. Budget is read-only in the QBO API (python-quickbooks: cannot be created via API).
**Alternatives rejected:** CSV / manual budget table (spec issue 3 options) - USER chose the entity.
**Consequences:** seed_sandbox.py cannot POST budgets; sandbox budgets must be created in the QBO UI. Quarterly / Yearly budgets need a spreading rule (test fails loudly today).
**Revisit-when:** a client keeps budgets outside QBO.
**Decided-by:** user
**Related:** DEC-002
**Status:** active

### DEC-005 · vw_fact_gl = P&L lines only (classification filter, not stmt_section) · 2026-09-26
**Decision:** vw_fact_gl keeps non-voided, non-deleted fact_gl lines whose account classification is Revenue or Expense; fact_gl keeps every line (balance-sheet JE sides) for V3 / audit.
**Context:** USER 2026-09-26 (spec 2.4 deviation); unfiltered PBI `Amount` would include Checking / Payroll Liabilities JE sides.
**Alternatives rejected:** filter on stmt_section (unmapped P&L accounts would vanish silently, CAND-002 pattern); drop balance-sheet lines from fact_gl (loses audit trail).
**Consequences:** demo vw_fact_gl 5831 rows (96 JE balance-sheet lines excluded); singular test assert_vw_fact_gl_pnl_scope guards both directions.
**Revisit-when:** a balance-sheet report enters scope.
**Decided-by:** user
**Related:** ISS-005
**Status:** active

### DEC-006 · Sales-line account = ItemAccountRef, else Item.IncomeAccountRef · 2026-09-26
**Decision:** SalesItemLineDetail resolves to the line's ItemAccountRef (QBO posting account) when present, else the item's current IncomeAccountRef; same path for Invoice, SalesReceipt, CreditMemo, RefundReceipt.
**Context:** USER 2026-09-26 (spec 3.1 deviation); an item's income account changed after posting would otherwise re-attribute history.
**Alternatives rejected:** spec rule (item lookup only).
**Consequences:** demo omits ItemAccountRef in month 1 (169 of 4628 sales lines) so the fallback runs on real data too; demo_summary.py mirrors the rule.
**Revisit-when:** sandbox fixtures show lines without ItemAccountRef in a pattern we should model.
**Decided-by:** user
**Related:** ISS-004
**Status:** active
