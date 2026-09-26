{% macro assert_migration_owned() %}
    {#-
        ADR-0002: dim_* / fact_* tables are created by migrations; dbt only fills them.
        qbo_etl holds CREATE on schema qbo (for the views), so a missing table would otherwise
        be created by dbt as qbo_etl. Stop instead: the table must exist (apply the migrations),
        and a full refresh is never allowed (full_refresh: false is set in dbt_project.yml too).
        Unit tests on these models override is_incremental to true.
    -#}
    {%- if execute and not is_incremental() -%}
        {{ exceptions.raise_compiler_error(
            "qbo_pnl: " ~ this ~ " is a migration-owned table (ADR-0002). It was not found as a "
            ~ "table in the target, or a full refresh was requested. Apply the supabase/migrations "
            ~ "first; dbt never creates or replaces it."
        ) }}
    {%- endif -%}
{% endmacro %}
