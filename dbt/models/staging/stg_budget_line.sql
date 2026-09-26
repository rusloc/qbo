-- QBO Budget entity exploded to one row per BudgetDetail entry (USER 2026-09-26: budgets come
-- from the Budget entity). All budgets pass through; fact_budget keeps active ProfitAndLoss
-- budgets. Amounts are in P&L presentation sign (income and expense both positive), the same
-- convention as fact_gl.amount_signed.
with budget as (
    select
         e.qbo_id                                                  budget_qbo_id
        ,e.payload                                                 payload
        ,coalesce((e.payload ->> 'Active')::boolean, true)
             and not e.is_deleted                                  is_active
    from {{ ref('stg_entity_latest') }} e
    where 1=1
        and e.entity_type = 'Budget'
)
select
     b.budget_qbo_id                                               budget_qbo_id
    ,b.payload ->> 'Name'                                          budget_name
    ,b.payload ->> 'BudgetType'                                    budget_type
    ,b.payload ->> 'BudgetEntryType'                               budget_entry_type
    ,b.is_active                                                   is_active
    ,d.detail_num::integer                                         detail_num
    ,date_trunc('month', (d.detail ->> 'BudgetDate')::timestamp)::date
                                                                   budget_month
    ,d.detail -> 'AccountRef' ->> 'value'                          account_qbo_id
    ,d.detail -> 'ClassRef' ->> 'value'                            class_qbo_id
    ,d.detail -> 'CustomerRef' ->> 'value'                         customer_qbo_id
    ,(d.detail ->> 'Amount')::numeric(15,2)                        amount
from budget b
cross join lateral jsonb_array_elements(b.payload -> 'BudgetDetail') with ordinality d(detail, detail_num)
