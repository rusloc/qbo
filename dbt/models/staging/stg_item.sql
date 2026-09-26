-- QBO Item, latest version: the account resolution for item-based lines (spec 3.1).
select
     e.qbo_id                                                      qbo_id
    ,e.payload ->> 'Name'                                          item_name
    ,e.payload ->> 'Type'                                          item_type
    ,e.payload -> 'IncomeAccountRef' ->> 'value'                   income_account_qbo_id
    ,e.payload -> 'ExpenseAccountRef' ->> 'value'                  expense_account_qbo_id
    ,coalesce((e.payload ->> 'Active')::boolean, true)
         and not e.is_deleted                                      is_active
from {{ ref('stg_entity_latest') }} e
where 1=1
    and e.entity_type = 'Item'
