-- Serve view for Power BI (spec 2.4): monthly budget per account (and class, when budgeted by
-- class). amount uses the P&L presentation sign, like vw_fact_gl.amount_signed.
-- date_key = first day of budget_month, for the vw_dim_date relationship.
select
     b.budget_key                                                  budget_key
    ,(to_char(b.budget_month::timestamp, 'YYYYMMDD'))::integer     date_key
    ,b.budget_month                                                budget_month
    ,b.account_key                                                 account_key
    ,b.class_key                                                   class_key
    ,b.amount                                                      amount
from {{ ref('fact_budget') }} b
