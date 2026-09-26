{{
    config(
        incremental_strategy='merge',
        unique_key='qbo_id',
        merge_exclude_columns=['stmt_section', 'stmt_group', 'stmt_sort'],
    )
}}
{{ assert_migration_owned() }}
-- Fills migration-owned qbo.dim_account (merge on qbo_id, ADR-0002). Inactive accounts stay.
-- stmt_section / stmt_group / stmt_sort are the consultant mapping layer: the defaults below
-- apply on INSERT only (merge_exclude_columns), so later consultant edits are never overwritten.
--   stmt_section: spec 3.3 auto-map from AccountType (other types stay null = off the P&L).
--   stmt_group:   top-level account of the branch (first FullyQualifiedName segment), P&L only.
--   stmt_sort:    AcctNum when numeric, else the QBO Id (creation order).
-- Every text column is cast to the table's exact varchar(n): dbt's incremental path otherwise
-- tries to widen the target columns (ALTER TABLE), which qbo_etl may not do.
with account as (
    select
         s.qbo_id                                                  qbo_id
        ,s.account_name                                            account_name
        ,s.fully_qualified                                         fully_qualified
        ,s.account_type                                            account_type
        ,s.account_subtype                                         account_subtype
        ,s.classification                                          classification
        ,s.parent_qbo_id                                           parent_qbo_id
        ,s.is_active                                               is_active
        ,s.acct_num                                                acct_num
        ,case s.account_type
             when 'Income'
                 then 'Revenue'
             when 'Cost of Goods Sold'
                 then 'COGS'
             when 'Expense'
                 then 'OpEx'
             when 'Other Income'
                 then 'OtherInc'
             when 'Other Expense'
                 then 'OtherExp'
         end                                                       stmt_section
    from {{ ref('stg_account') }} s
)
select
     a.qbo_id::varchar(20)                                         qbo_id
    ,a.account_name::varchar(200)                                  account_name
    ,a.fully_qualified::varchar(400)                               fully_qualified
    ,a.account_type::varchar(50)                                   account_type
    ,a.account_subtype::varchar(80)                                account_subtype
    ,a.classification::varchar(20)                                 classification
    ,a.parent_qbo_id::varchar(20)                                  parent_qbo_id
    ,a.is_active                                                   is_active
    ,a.stmt_section::varchar(40)                                   stmt_section
    ,case
         when a.stmt_section is not null
             then split_part(coalesce(a.fully_qualified, a.account_name), ':', 1)
     end::varchar(80)                                              stmt_group
    ,case
         when a.acct_num ~ '^[0-9]{1,9}$'
             then a.acct_num::integer
         when a.qbo_id ~ '^[0-9]{1,9}$'
             then a.qbo_id::integer
     end                                                           stmt_sort
from account a
