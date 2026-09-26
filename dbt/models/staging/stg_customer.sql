-- QBO Customer, latest version (inactive customers kept).
-- payment_terms: QBO usually sends only the Term Id in SalesTermRef; the Term entity is not
-- landed, so the name is used when present, else the Id.
select
     e.qbo_id                                                      qbo_id
    ,e.payload ->> 'DisplayName'                                   display_name
    ,e.payload -> 'ParentRef' ->> 'value'                          parent_qbo_id
    ,coalesce((e.payload ->> 'Active')::boolean, true)
         and not e.is_deleted                                      is_active
    ,coalesce(
         e.payload -> 'SalesTermRef' ->> 'name'
        ,e.payload -> 'SalesTermRef' ->> 'value'
     )                                                             payment_terms
from {{ ref('stg_entity_latest') }} e
where 1=1
    and e.entity_type = 'Customer'
