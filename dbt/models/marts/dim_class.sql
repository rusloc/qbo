{{
    config(
        incremental_strategy='merge',
        unique_key='qbo_id',
    )
}}
{{ assert_migration_owned() }}
-- Fills migration-owned qbo.dim_class (merge on qbo_id, ADR-0002). Inactive classes stay.
select
     c.qbo_id::varchar(20)                                         qbo_id
    ,c.class_name::varchar(120)                                    class_name
from {{ ref('stg_class') }} c
