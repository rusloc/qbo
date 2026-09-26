<!-- next-id: ISS-008 -->

# Issues

### ISS-001 · stmt_group / stmt_sort insert-only defaults need USER review · opened 2026-09-26
**Pipeline:** dbt qbo_pnl
**Issue:** proposed defaults: stmt_group = first FullyQualifiedName segment (P&L accounts), stmt_sort = numeric AcctNum else QBO Id.
**Impact:** P&L matrix hierarchy / order in PBI; per-account stmt_sort cannot be a sort-by column for stmt_section or stmt_group (bip).
**Owner:** user
**Next step:** USER accepts or gives a mapping; bip handles section order via pnl_layout.
**Related:** DEC-003
**Status:** open

### ISS-002 · Demo and real data cannot coexist in schema qbo · opened 2026-09-26
**Pipeline:** demo_load, qbo_sync
**Issue:** raw_entity has no realm/source column; demo Ids collide with sandbox Ids and newer synced_at wins per object -> mixed dataset.
**Impact:** switching demo -> sandbox needs a raw purge (qbo_etl has no DELETE on raw_entity; destructive, USER-run) plus fact/dim reset.
**Owner:** user / main session
**Next step:** decide the switch procedure before the first real backfill (purge statement run by USER, or a separate schema/project).
**Status:** open

### ISS-003 · Spec 3.1 coverage gaps vs real QBO data · opened 2026-09-26
**Pipeline:** dbt qbo_pnl
**Issue:** not transformed: Deposit (DepositLineDetail to income), VendorCredit (flip), GroupLineDetail bundles, Inventory-item COGS (posted by QBO at sale, not in any Line; purchases post to the asset account).
**Impact:** V1 reconciliation fails for clients using them; demo avoids them (NonInventory / Service items only).
**Owner:** user (scope) / ferry (models)
**Next step:** USER decides scope after sandbox fixtures (Track A); detail_type accepted_values test fails loudly on bundles.
**Related:** SRC-001
**Status:** open

### ISS-004 · SalesItemLineDetail.ItemAccountRef vs Item.IncomeAccountRef · opened 2026-09-26
**Pipeline:** dbt qbo_pnl
**Issue:** spec resolves via the item's current income account; QBO returns the line's posting account in ItemAccountRef. Diverge if an item's account changes after posting.
**Owner:** user
**Next step:** none.
**Related:** DEC-006
**Status:** resolved 2026-09-26 (USER chose ItemAccountRef first, item fallback; implemented + unit tests)

### ISS-005 · Balance-sheet JE sides in vw_fact_gl; V2 scope · opened 2026-09-26
**Pipeline:** dbt qbo_pnl -> PBI
**Issue:** JE lines to Checking / Payroll Liabilities / Accumulated Depreciation are in fact_gl (spec 3.2 signs them); spec V2 would flag them as unmapped; unfiltered PBI `Amount` includes them.
**Owner:** bip (measures), db-chef (V2 SQL)
**Next step:** db-chef scopes the V2 validation SQL to classification Revenue/Expense (dbt warn test assert_pnl_accounts_mapped already does). vw_fact_gl part resolved by DEC-005.
**Related:** DEC-005
**Status:** open (vw_fact_gl scope resolved 2026-09-26; V2 SQL remains)

### ISS-006 · dbt SQL not yet executed against Postgres · opened 2026-09-26
**Pipeline:** dbt qbo_pnl
**Issue:** verified only by dbt parse, offline compile + sqlglot postgres parse (100/100) and the Python reference (demo_summary.py); no DB run allowed this session.
**Owner:** user (runs), ferry (fixes)
**Next step:** USER runs load_demo.py, run_dbt.py build x2, run-operation qbo_demo_check; compare with demo_summary.py.
**Related:** DEC-001
**Status:** open

### ISS-007 · payment_terms holds the Term Id · opened 2026-09-26
**Pipeline:** qbo_sync -> dbt
**Issue:** Customer.SalesTermRef usually carries only the Id; the Term entity is not landed.
**Owner:** ferry (B lane: add Term to NAME_LISTS) / user
**Next step:** decide whether dim_customer.payment_terms matters for v1.
**Status:** open
