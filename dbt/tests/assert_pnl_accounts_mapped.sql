{{ config(severity='warn') }}
-- Spec 3.3 / 5 V2 (unmapped accounts), scoped to P&L classifications: a Revenue / Expense
-- account with GL activity and no stmt_section drops out of every section measure. Balance-sheet
-- accounts (journal entry sides) are expected to stay unmapped. Fix: set stmt_section in
-- dim_account (consultant mapping; dbt keeps the edit).
select
     a.qbo_id                                                      _qbo_id
    ,a.fully_qualified                                             _account
    ,a.account_type                                                _account_type
from {{ ref('dim_account') }} a
where 1=1
    and a.stmt_section is null
    and a.classification in ('Revenue', 'Expense')
    and exists (
        select
             1                                                     _one
        from {{ ref('fact_gl') }} g
        where 1=1
            and g.account_key = a.account_key
    )
