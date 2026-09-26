-- Latest version of every QBO object in the insert-only raw zone (spec 2.1): one row per
-- (entity_type, qbo_id), newest synced_at first.
-- is_deleted: the newest version is a CDC delete marker ({"status": "Deleted"}); payload then
--   keeps the last full body, so fact_gl flags the lines of a deleted transaction instead of
--   silently keeping them unflagged.
-- is_voided: QBO voids keep the document with PrivateNote "Voided" and amounts zeroed.
-- Every entity type passes through (Deposit, VendorCredit, ... included); downstream models
-- pick the types they transform.
with versions as (
    select
         r.entity_type                                             entity_type
        ,r.qbo_id                                                  qbo_id
        ,r.payload                                                 payload
        ,r.synced_at                                               synced_at
        ,coalesce(r.payload ->> 'status', '') = 'Deleted'          is_delete_marker
    from {{ source('qbo', 'raw_entity') }} r
)
,ranked as (
    select
         v.entity_type                                             entity_type
        ,v.qbo_id                                                  qbo_id
        ,v.payload                                                 payload
        ,v.synced_at                                               synced_at
        ,v.is_delete_marker                                        is_delete_marker
        ,row_number() over (
             partition by v.entity_type, v.qbo_id
             order by v.synced_at desc
         )                                                         version_rank
        ,row_number() over (
             partition by v.entity_type, v.qbo_id, v.is_delete_marker
             order by v.synced_at desc
         )                                                         kind_rank
    from versions v
)
,latest as (
    select
         l.entity_type                                             entity_type
        ,l.qbo_id                                                  qbo_id
        ,coalesce(b.payload, l.payload)                            payload
        ,l.is_delete_marker                                        is_deleted
        ,l.synced_at                                               synced_at
    from ranked l
    left join ranked b
        on b.entity_type = l.entity_type
        and b.qbo_id = l.qbo_id
        and b.is_delete_marker = false
        and b.kind_rank = 1
    where 1=1
        and l.version_rank = 1
)
select
     t.entity_type                                                 entity_type
    ,t.qbo_id                                                      qbo_id
    ,t.payload                                                     payload
    ,t.is_deleted                                                  is_deleted
    ,case
         when coalesce(t.payload ->> 'status', '') = 'Voided'
             then true
         when coalesce(t.payload ->> 'PrivateNote', '') ilike 'voided%'
             and coalesce((t.payload ->> 'TotalAmt')::numeric, 0) = 0
             then true
         else false
     end                                                           is_voided
    ,t.synced_at                                                   synced_at
from latest t
