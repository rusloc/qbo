{{
    config(
        incremental_strategy='delete+insert',
        unique_key=['txn_type', 'txn_qbo_id'],
    )
}}
{{ assert_migration_owned() }}
-- Fills migration-owned qbo.fact_gl (ADR-0002): delete+insert per transaction, so a re-synced
-- transaction replaces ALL its lines (a line removed in QBO disappears here too).
-- Incremental path: transactions whose latest raw version is at or after the newest
-- source_sync_at already loaded (>=: the last batch is re-applied, harmless). Full reprocess:
--   run_dbt.py build --vars "{full_reload: true}"
-- account_key is a LEFT join on purpose: an unresolved account fails loudly on the NOT NULL
-- constraint (and on the stg_txn_line tests before that) instead of dropping the line.
select
     s.txn_type::varchar(30)                                       txn_type
    ,s.txn_qbo_id::varchar(20)                                     txn_qbo_id
    ,s.line_num                                                    line_num
    ,s.txn_date                                                    txn_date
    ,a.account_key                                                 account_key
    ,c.customer_key                                                customer_key
    ,v.vendor_key                                                  vendor_key
    ,k.class_key                                                   class_key
    ,s.amount_signed                                               amount_signed
    ,left(s.memo, 500)::varchar(500)                               memo
    ,s.is_voided                                                   is_voided
    ,s.is_deleted                                                  is_deleted
    ,s.synced_at                                                   source_sync_at
from {{ ref('stg_txn_line') }} s
left join {{ ref('dim_account') }} a
    on a.qbo_id = s.account_qbo_id
left join {{ ref('dim_customer') }} c
    on c.qbo_id = s.customer_qbo_id
left join {{ ref('dim_vendor') }} v
    on v.qbo_id = s.vendor_qbo_id
left join {{ ref('dim_class') }} k
    on k.qbo_id = s.class_qbo_id
where 1=1
    and s.is_posting
{%- if is_incremental() and not var('full_reload') %}
    and s.synced_at >= (
        select
             coalesce(max(f.source_sync_at), '-infinity'::timestamptz) _max_sync_at
        from {{ this }} f
    )
{%- endif %}
