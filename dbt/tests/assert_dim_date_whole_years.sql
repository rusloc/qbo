-- dim_date must be contiguous and span whole calendar years (Power BI date table), and cover
-- every fact_gl date. Returns a row when any of that is broken.
with span as (
    select
         min(t.d)                                                  _first_d
        ,max(t.d)                                                  _last_d
        ,count(*)                                                  _days_cnt
    from {{ ref('dim_date') }} t
)
,fact as (
    select
         min(g.txn_date)                                           _first_txn
        ,max(g.txn_date)                                           _last_txn
    from {{ ref('fact_gl') }} g
)
select
     s._first_d                                                    _first_d
    ,s._last_d                                                     _last_d
    ,s._days_cnt                                                   _days_cnt
    ,f._first_txn                                                  _first_txn
    ,f._last_txn                                                   _last_txn
from span s
cross join fact f
where 1=1
    and s._days_cnt > 0
    and (
        s._days_cnt <> s._last_d - s._first_d + 1
        or extract(month from s._first_d) <> 1
        or extract(day from s._first_d) <> 1
        or extract(month from s._last_d) <> 12
        or extract(day from s._last_d) <> 31
        or f._first_txn < s._first_d
        or f._last_txn > s._last_d
    )
