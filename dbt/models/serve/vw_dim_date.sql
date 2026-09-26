-- Serve view for Power BI (spec 2.4): contiguous calendar (whole years), mark as date table.
select
     t.date_key                                                    date_key
    ,t.d                                                           d
    ,t.y                                                           y
    ,t.q                                                           q
    ,t.m                                                           m
    ,t.month_name                                                  month_name
    ,t.year_month                                                  year_month
    ,t.fiscal_year                                                 fiscal_year
    ,t.fiscal_period                                               fiscal_period
    ,t.week_start                                                  week_start
    ,t.is_month_end                                                is_month_end
from {{ ref('dim_date') }} t
