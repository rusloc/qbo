{{
    config(
        incremental_strategy='append',
        pre_hook="delete from {{ this }}",
    )
}}
{{ assert_migration_owned() }}
-- Fills migration-owned qbo.fact_budget from the QBO Budget entity (USER 2026-09-26).
-- Full replace in ONE transaction: the pre-hook delete and the insert run between dbt's BEGIN
-- and COMMIT, so readers never see an empty table and a failure rolls back to the old rows.
-- Why not merge / delete+insert on (budget_month, account_key, class_key): dbt matches keys
-- with "=", so a null class_key never matches and the insert collides with the table's
-- unique nulls not distinct constraint; and a deactivated budget would leave stale rows.
-- Size: ~30 rows per budget month, so the full replace costs nothing.
-- Keeps active ProfitAndLoss budgets; amounts are summed over customer / location subdivisions.
select
     b.budget_month                                                budget_month
    ,a.account_key                                                 account_key
    ,c.class_key                                                   class_key
    ,sum(b.amount)::numeric(15,2)                                  amount
from {{ ref('stg_budget_line') }} b
left join {{ ref('dim_account') }} a
    on a.qbo_id = b.account_qbo_id
left join {{ ref('dim_class') }} c
    on c.qbo_id = b.class_qbo_id
where 1=1
    and b.is_active
    and b.budget_type = 'ProfitAndLoss'
group by
     b.budget_month
    ,a.account_key
    ,c.class_key
