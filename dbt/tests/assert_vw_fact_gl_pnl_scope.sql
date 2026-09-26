-- vw_fact_gl scope (USER 2026-09-26): exactly the non-voided, non-deleted fact_gl lines on
-- Revenue / Expense accounts. Fails on a balance-sheet line in the view, and on a P&L line the
-- view lost (e.g. a later filter on stmt_section would drop unmapped P&L accounts silently).
with expected as (
    select
         g.gl_key                                                  _gl_key
    from {{ ref('fact_gl') }} g
    join {{ ref('dim_account') }} a on a.account_key = g.account_key
    where 1=1
        and g.is_voided = false
        and g.is_deleted = false
        and a.classification in ('Revenue', 'Expense')
)
,served as (
    select
         v.gl_key                                                  _gl_key
    from {{ ref('vw_fact_gl') }} v
)
select
     coalesce(e._gl_key, s._gl_key)                                _gl_key
    ,case
         when e._gl_key is null
             then 'in vw_fact_gl but not a P&L line'
         else 'P&L line missing from vw_fact_gl'
     end                                                           _problem
from expected e
full join served s on s._gl_key = e._gl_key
where 1=1
    and (
        e._gl_key is null
        or s._gl_key is null
    )
