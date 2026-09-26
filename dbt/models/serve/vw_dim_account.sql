-- Serve view for Power BI (spec 2.4): chart of accounts with the consultant mapping layer.
-- stmt_section null = not on the P&L (balance-sheet accounts, or not mapped yet).
select
     a.account_key                                                 account_key
    ,a.qbo_id                                                      qbo_id
    ,a.account_name                                                account_name
    ,a.fully_qualified                                             fully_qualified
    ,a.account_type                                                account_type
    ,a.account_subtype                                             account_subtype
    ,a.classification                                              classification
    ,a.parent_qbo_id                                               parent_qbo_id
    ,a.is_active                                                   is_active
    ,a.stmt_section                                                stmt_section
    ,a.stmt_group                                                  stmt_group
    ,a.stmt_sort                                                   stmt_sort
from {{ ref('dim_account') }} a
