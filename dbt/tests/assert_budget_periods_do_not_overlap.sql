-- Two active ProfitAndLoss budgets covering the same month would be summed into fact_budget
-- (double budget). Returns the offending months; deactivate one budget in QBO to fix.
select
     l.budget_month                                                _budget_month
    ,count(distinct l.budget_qbo_id)                               _active_budgets_cnt
    ,string_agg(distinct l.budget_name, ' | ')                     _budget_names
from {{ ref('stg_budget_line') }} l
where 1=1
    and l.is_active
    and l.budget_type = 'ProfitAndLoss'
group by l.budget_month
having count(distinct l.budget_qbo_id) > 1
