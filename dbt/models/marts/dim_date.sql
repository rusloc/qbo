{{
    config(
        incremental_strategy='merge',
        unique_key='date_key',
    )
}}
{{ assert_migration_owned() }}
{%- set fy_start = var('fy_start') | int -%}
{%- if fy_start < 1 or fy_start > 12 -%}
    {{ exceptions.raise_compiler_error("qbo_pnl: var fy_start must be a month number 1..12") }}
{%- endif %}
-- Fills migration-owned qbo.dim_date (merge on date_key; dim_date has no qbo_id). The spine
-- covers whole calendar years around every TxnDate and Budget period landed, so Power BI can
-- mark it as a date table (contiguous, no gaps). Dates are never deleted.
-- Fiscal columns from var fy_start (spec 2.2, default 1). A fiscal year is named by the calendar
-- year it ends in: with fy_start 7, 2025-07-01 .. 2026-06-30 is fiscal_year 2026.
with bound as (
    select
         e.payload ->> 'TxnDate'                                   d
    from {{ ref('stg_entity_latest') }} e
    where 1=1
        and e.payload ->> 'TxnDate' is not null
    union all
    select
         e.payload ->> 'StartDate'                                 d
    from {{ ref('stg_entity_latest') }} e
    where 1=1
        and e.entity_type = 'Budget'
        and e.payload ->> 'StartDate' is not null
    union all
    select
         e.payload ->> 'EndDate'                                   d
    from {{ ref('stg_entity_latest') }} e
    where 1=1
        and e.entity_type = 'Budget'
        and e.payload ->> 'EndDate' is not null
)
,span as (
    select
         make_date(extract(year from min(b.d::date))::integer, 1, 1)   first_d
        ,make_date(extract(year from max(b.d::date))::integer, 12, 31) last_d
    from bound b
)
,spine as (
    select
         s.first_d + g.n                                           d
    from span s
    cross join lateral generate_series(0, s.last_d - s.first_d) g(n)
)
,parts as (
    select
         p.d                                                       d
        ,extract(year from p.d)::integer                           y
        ,extract(quarter from p.d)::integer                        qn
        ,extract(month from p.d)::integer                          m
        ,extract(day from p.d)::integer                            dd
        ,extract(isodow from p.d)::integer                         isodow
    from spine p
)
select
     (t.y * 10000 + t.m * 100 + t.dd)::integer                     date_key
    ,t.d                                                           d
    ,t.y                                                           y
    ,('Q' || t.qn)::varchar(2)                                     q
    ,t.m                                                           m
    ,to_char(t.d::timestamp, 'FMMonth')::varchar(12)               month_name
    ,to_char(t.d::timestamp, 'YYYY-MM')::varchar(7)                year_month
    ,case
         when {{ fy_start }} > 1
             and t.m >= {{ fy_start }}
             then t.y + 1
         else t.y
     end                                                           fiscal_year
    ,mod(t.m - {{ fy_start }} + 12, 12) + 1                        fiscal_period
    ,t.d - (t.isodow - 1)                                          week_start
    ,extract(day from t.d + 1) = 1                                 is_month_end
from parts t
