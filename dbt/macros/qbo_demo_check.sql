{% macro qbo_demo_check() %}
    {#-
        Read-only check after `dbt build`: row counts per table / view and P&L per data year and
        stmt_section from the serve views (P&L lines only; unmapped P&L accounts show as
        '(unmapped)'). Compare with `etl/demo_summary.py` (same numbers).
        Run: etl/.venv/Scripts/python etl/run_dbt.py run-operation qbo_demo_check
    -#}
    {% set objects = [
        ('raw_entity', source('qbo', 'raw_entity')),
        ('dim_account', ref('dim_account')),
        ('dim_customer', ref('dim_customer')),
        ('dim_vendor', ref('dim_vendor')),
        ('dim_class', ref('dim_class')),
        ('dim_date', ref('dim_date')),
        ('fact_gl', ref('fact_gl')),
        ('vw_fact_gl', ref('vw_fact_gl')),
        ('fact_budget', ref('fact_budget')),
        ('vw_fact_budget', ref('vw_fact_budget')),
    ] %}
    {% set pnl_sql %}
        with line as (
            select
                 case
                     when g.txn_date < date '2025-09-01'
                         then 'year1'
                     else 'year2'
                 end                                               _data_year
                ,coalesce(a.stmt_section, '(unmapped)')            _stmt_section
                ,g.amount_signed                                   _amount_signed
            from {{ ref('vw_fact_gl') }} g
            join {{ ref('vw_dim_account') }} a on a.account_key = g.account_key
            where 1=1
                and g.txn_date between date '2024-09-01' and date '2026-08-31'
        )
        select
             l._data_year                                          _data_year
            ,l._stmt_section                                       _stmt_section
            ,sum(l._amount_signed)                                 _amount
        from line l
        group by l._data_year, l._stmt_section
        order by l._data_year, l._stmt_section
    {% endset %}
    {% if execute %}
        {{ print("Row counts") }}
        {% for name, relation in objects %}
            {% set count_sql %}
                select
                     count(*)                                      _rows_cnt
                from {{ relation }} r
            {% endset %}
            {{ print("  " ~ name ~ ": " ~ run_query(count_sql).columns[0].values()[0]) }}
        {% endfor %}
        {{ print("P&L by data year and stmt_section (vw_fact_gl)") }}
        {% for row in run_query(pnl_sql) %}
            {{ print("  " ~ row[0] ~ " " ~ row[1] ~ ": " ~ row[2]) }}
        {% endfor %}
    {% endif %}
{% endmacro %}
