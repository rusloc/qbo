-- 20260925213800_qbo_init_schema_and_roles
-- F-05 M1 | ADR-0003 (schema qbo, roles, grants) | ADR-0008 (qbo namespace, qbo_ prefix)
-- Creates schema qbo and the nologin roles qbo_etl / qbo_reader with their schema-level grants.

create schema qbo;

comment on schema qbo is 'QBO P&L warehouse (repo rusloc/qbo). Isolated per ADR-0008; layout ADR-0003.';

create role qbo_etl    nologin;
create role qbo_reader nologin;

comment on role qbo_etl    is 'QBO P&L: ETL (qbo_sync) + dbt. DML on qbo tables, creates qbo views.';
comment on role qbo_reader is 'QBO P&L: Power BI. Reads qbo.vw_* only.';

grant usage
    on schema qbo
    to qbo_etl
      ,qbo_reader;

grant create
    on schema qbo
    to qbo_etl;        -- dbt creates stg_* / vw_* views
