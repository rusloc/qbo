{{
    config(
        incremental_strategy='merge',
        unique_key='qbo_id',
    )
}}
{{ assert_migration_owned() }}
-- Fills migration-owned qbo.dim_vendor (merge on qbo_id, ADR-0002). Inactive vendors stay.
select
     v.qbo_id::varchar(20)                                         qbo_id
    ,v.display_name::varchar(200)                                  display_name
    ,v.is_active                                                   is_active
from {{ ref('stg_vendor') }} v
