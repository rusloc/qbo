<!-- next-id: ANTI-002 -->

# Antipatterns

### ANTI-001 · Silent row loss through nullable or unconstrained filter keys · 2026-09-25
**Antipattern:** A column that downstream code filters or joins on (`= false`, `= 'OpEx'`, `on a.k = b.k`) is left nullable or free-text. A null / typo does not error — the row just vanishes from the measure, the view or the reconciliation.
**Where seen:** (1) `fact_gl.is_voided` / `is_deleted` — spec had `default false` without `not null`; `vw_fact_gl` filters `= false`, a null row disappears (fixed: `not null` in M4). (2) `dim_account.stmt_section` — free `varchar(40)`; a consultant typo drops the account from every spec §7 DAX measure (fixed: `dim_account_stmt_section_check` in M3). (3) `qbo.qa_reports_snapshot` — `report`, `period_month`, `section` all nullable, no PK; V1 compares per `period_month x section`, a null key silently shrinks the comparison set (open: spec-shaped, accepted in ADR-0003 as an INFO notice).
**Why we refuse it:** spec §5 says "fail loudly, tolerance $0.01"; a filter key that can be null fails silently instead. Cost of the fix is one `not null` / one `check`; cost of the miss is a reconciliation that passes while rows are missing.
**Reversibility:** high (constraints can be added later, but only after cleaning the data that already slipped through)
**Hits:** 3
**Tags:** not-null, check-constraint, reconciliation, silent-drop, filter-key
**Confidence:** medium (3 sightings, no template needed)
**Last-verified:** 2026-09-25
**Related:** —
**Status:** active — proposed to the main session as project anti-pattern candidate (see journal 2026-09-25)
