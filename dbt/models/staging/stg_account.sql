-- QBO Account, latest version. Inactive accounts stay (the backfill queries Active in (true,
-- false)): they can carry GL history, and dropping them would orphan fact_gl lines.
select
     e.qbo_id                                                      qbo_id
    ,e.payload ->> 'Name'                                          account_name
    ,e.payload ->> 'FullyQualifiedName'                            fully_qualified
    ,e.payload ->> 'AccountType'                                   account_type
    ,e.payload ->> 'AccountSubType'                                account_subtype
    ,e.payload ->> 'Classification'                                classification
    ,e.payload -> 'ParentRef' ->> 'value'                          parent_qbo_id
    ,e.payload ->> 'AcctNum'                                       acct_num
    ,coalesce((e.payload ->> 'Active')::boolean, true)
         and not e.is_deleted                                      is_active
    ,e.synced_at                                                   synced_at
from {{ ref('stg_entity_latest') }} e
where 1=1
    and e.entity_type = 'Account'
