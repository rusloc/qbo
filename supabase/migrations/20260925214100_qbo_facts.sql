-- 20260925214100_qbo_facts
-- F-05 M4 | spec 2.3 | ADR-0002 (dbt fills fact_gl via delete+insert per transaction) | ADR-0003 (qbo_etl grants; unindexed FKs accepted at v1 volume)
-- Creates fact_gl (exploded, sign-normalized GL lines) and fact_budget (created empty; budget source is spec issue 3).

create table qbo.fact_gl (
     gl_key           bigint         generated always as identity primary key
    ,txn_type         varchar(30)    not null
    ,txn_qbo_id       varchar(20)    not null
    ,line_num         integer        not null
    ,txn_date         date           not null
    ,account_key      integer        not null references qbo.dim_account (account_key)
    ,customer_key     integer        references qbo.dim_customer (customer_key)
    ,vendor_key       integer        references qbo.dim_vendor (vendor_key)
    ,class_key        integer        references qbo.dim_class (class_key)
    ,amount_signed    numeric(15,2)  not null
    ,memo             varchar(500)
    ,is_voided        boolean        not null default false
    ,is_deleted       boolean        not null default false
    ,source_sync_at   timestamptz
    ,unique (txn_type, txn_qbo_id, line_num)
);

create table qbo.fact_budget (
     budget_key       bigint         generated always as identity primary key
    ,budget_month     date           not null
    ,account_key      integer        not null references qbo.dim_account (account_key)
    ,class_key        integer        references qbo.dim_class (class_key)
    ,amount           numeric(15,2)  not null
    ,unique nulls not distinct (budget_month, account_key, class_key)
);

grant select, insert, update, delete
    on qbo.fact_gl
      ,qbo.fact_budget
    to qbo_etl;
