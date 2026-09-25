-- 20260925213900_qbo_raw_and_control
-- F-05 M2 | spec 2.1 / 2.3 | ADR-0003 (qbo_etl grants; raw zone insert-only)
-- Creates the landed-JSON raw zone and the ETL control tables: raw_entity, sync_state, qa_reports_snapshot.

create table qbo.raw_entity (
     entity_type      varchar(30)    not null      -- 'Invoice', 'Bill', 'Account', ...
    ,qbo_id           varchar(20)    not null
    ,payload          jsonb          not null
    ,synced_at        timestamptz    not null
    ,primary key (entity_type, qbo_id, synced_at)
);

create table qbo.sync_state (
     entity_type      varchar(30)    primary key
    ,watermark        timestamptz
    ,last_status      varchar(20)
    ,last_run         timestamptz
    ,rows_upserted    integer
);

create table qbo.qa_reports_snapshot (
     report           varchar(40)
    ,period_month     date
    ,section          varchar(40)
    ,amount           numeric(15,2)
    ,captured_at      timestamptz
);

grant select, insert
    on qbo.raw_entity              -- raw zone: insert-only
    to qbo_etl;

grant select, insert, update
    on qbo.sync_state
    to qbo_etl;

grant select, insert
    on qbo.qa_reports_snapshot
    to qbo_etl;
