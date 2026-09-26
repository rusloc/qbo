-- QBO Vendor, latest version (inactive vendors kept).
select
     e.qbo_id                                                      qbo_id
    ,e.payload ->> 'DisplayName'                                   display_name
    ,coalesce((e.payload ->> 'Active')::boolean, true)
         and not e.is_deleted                                      is_active
from {{ ref('stg_entity_latest') }} e
where 1=1
    and e.entity_type = 'Vendor'
