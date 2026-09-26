{{
    config(
        incremental_strategy='merge',
        unique_key='qbo_id',
    )
}}
{{ assert_migration_owned() }}
-- Fills migration-owned qbo.dim_customer (merge on qbo_id, ADR-0002). Inactive customers stay.
select
     c.qbo_id::varchar(20)                                         qbo_id
    ,c.display_name::varchar(200)                                  display_name
    ,c.parent_qbo_id::varchar(20)                                  parent_qbo_id
    ,c.is_active                                                   is_active
    ,c.payment_terms::varchar(50)                                  payment_terms
from {{ ref('stg_customer') }} c
