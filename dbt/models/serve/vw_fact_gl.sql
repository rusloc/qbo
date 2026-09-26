-- Serve view for Power BI (spec 2.4): posted P&L lines, voided and deleted transactions removed.
-- P&L scope (USER 2026-09-26, spec deviation): accounts with classification Revenue or Expense
-- only; the balance-sheet side of journal entries (Checking, Payroll Liabilities, ...) stays in
-- fact_gl for V3 / audit. The filter is on classification, NOT on stmt_section: a P&L account
-- without a mapping stays visible (blank section) instead of vanishing.
-- date_key joins vw_dim_date[date_key] (integer relationship key); txn_date stays for V1 (spec 5).
select
     g.gl_key                                                      gl_key
    ,(to_char(g.txn_date::timestamp, 'YYYYMMDD'))::integer         date_key
    ,g.txn_date                                                    txn_date
    ,g.txn_type                                                    txn_type
    ,g.txn_qbo_id                                                  txn_qbo_id
    ,g.line_num                                                    line_num
    ,g.account_key                                                 account_key
    ,g.customer_key                                                customer_key
    ,g.vendor_key                                                  vendor_key
    ,g.class_key                                                   class_key
    ,g.amount_signed                                               amount_signed
    ,g.memo                                                        memo
from {{ ref('fact_gl') }} g
join {{ ref('dim_account') }} a
    on a.account_key = g.account_key
where 1=1
    and g.is_voided = false
    and g.is_deleted = false
    and a.classification in ('Revenue', 'Expense')
