<!-- next-id: TOOL-003 -->
<!-- next-id: SRC-002 -->
<!-- Source / warehouse quirks folded in here (Scope field) until this file passes ~100 lines. -->

# Tool, source and warehouse quirks

### TOOL-001 · dbt incremental widens varchar columns of the target table · 2026-09-26
**Scope:** dbt-core 1.12.5 + dbt-adapters 1.24.5 + dbt-postgres 1.11.0; models filling migration-owned tables (ADR-0002)
**Symptom:** first `dbt build` of a mart would fail with "must be owner of table" (or, as owner, silently ALTER the migration schema to varchar(256)).
**Cause:** incremental materialization calls `adapter.expand_target_column_types(temp, target)` when no enforced contract exists; a `text` column in the temp relation counts as string_size 256 and any narrower varchar(n) target column is ALTERed.
**Fix / guard:** cast every string output of a mart model to the table's exact `::varchar(n)`; `etl/tests/test_dbt_marts_contract.py` checks casts, unknown columns and identity columns against `supabase/migrations/` statically.
**Seen:** dbt/adapters/sql/impl.py `expand_column_types`, global incremental.sql (read 2026-09-26); guard in dbt/models/marts/*.sql
**Hits:** 1
**Tags:** dbt, incremental, postgres, alter-table, varchar, migration-owned, adr-0002
**Confidence:** low
**Last-verified:** 2026-09-26
**Related:** DEC-003
**Status:** active

### TOOL-002 · dbt merge / delete+insert match list keys with "=" (nulls never match) · 2026-09-26
**Scope:** dbt-core 1.12.5 global `default__get_merge_sql` / `default__get_delete_insert_merge_sql`
**Symptom:** a unique key containing a nullable column (qbo.fact_budget class_key, `unique nulls not distinct`) re-inserts null-key rows on every run -> unique violation on run 2.
**Cause:** list unique_key -> `SOURCE.k = DEST.k` (merge) and `(k1, k2) in (select ...)` (delete+insert); only a single-string key uses the null-safe `equals()` macro, and only behind a behavior flag.
**Fix / guard:** fact_budget = `append` + pre-hook `delete from {{ this }}` (same transaction). See DEC-002.
**Seen:** db-chef note in .log/daily/daily-2026-09-25.md; macro source read 2026-09-26
**Hits:** 2
**Tags:** dbt, merge, delete+insert, null, unique-key, fact_budget
**Confidence:** medium
**Last-verified:** 2026-09-26
**Related:** DEC-002
**Status:** active

### SRC-001 · QBO lines: no Id/LineNum on SubTotal/Discount, JE ids from 0, void = zeroed doc · 2026-09-26
**Scope:** source: QBO Accounting API v3, minorversion 75
**Symptom:** keying fact lines on Line.Id / LineNum gives nulls (SubTotalLineDetail, DiscountLineDetail) and "0" for JE lines; voided docs have no flag field.
**Cause:** QBO response shapes (Intuit sample invoice; python-quickbooks object model); voids keep the doc with PrivateNote "Voided" and amounts / Qty zeroed (Intuit dev blog 2016, community answers).
**Fix / guard:** line_num = 1-based position in the Line array (`with ordinality`); is_voided = PrivateNote ilike 'voided%' and TotalAmt = 0, or status 'Voided' (CDC, unverified). dbt unit tests dt_sub_total_line_detail, dt_discount_line_detail, void_delete_flags_and_untransformed_types.
**Seen:** dbt/models/staging/stg_txn_line.sql, stg_entity_latest.sql (2026-09-26); sandbox fixtures not captured yet
**Hits:** 1
**Tags:** qbo, line, linenum, void, subtotal, discount, journal-entry
**Confidence:** low
**Last-verified:** 2026-09-26
**Related:** ISS-003
**Status:** active
