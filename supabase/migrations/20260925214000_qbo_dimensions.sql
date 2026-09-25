-- 20260925214000_qbo_dimensions
-- F-05 M3 | spec 2.2 | ADR-0002 (dbt fills via incremental merge on qbo_id) | ADR-0003 (qbo_etl grants)
-- Creates the five dimension tables; stmt_section is constrained to the spec 3.3 statement sections (null allowed until the consultant maps).

create table qbo.dim_account (
     account_key      integer        generated always as identity primary key
    ,qbo_id           varchar(20)    not null unique
    ,account_name     varchar(200)
    ,fully_qualified  varchar(400)
    ,account_type     varchar(50)
    ,account_subtype  varchar(80)
    ,classification   varchar(20)                  -- Asset | Liability | Equity | Revenue | Expense
    ,parent_qbo_id    varchar(20)
    ,is_active        boolean
    ,stmt_section     varchar(40)                  -- consultant mapping: Revenue | COGS | OpEx | OtherInc | OtherExp | Tax
    ,stmt_group       varchar(80)                  -- consultant mapping: e.g. Payroll, Marketing, Rent
    ,stmt_sort        integer                      -- consultant mapping
    ,constraint dim_account_stmt_section_check
        check (stmt_section in ('Revenue', 'COGS', 'OpEx', 'OtherInc', 'OtherExp', 'Tax'))
);

create table qbo.dim_customer (
     customer_key     integer        generated always as identity primary key
    ,qbo_id           varchar(20)    not null unique
    ,display_name     varchar(200)
    ,parent_qbo_id    varchar(20)
    ,is_active        boolean
    ,payment_terms    varchar(50)
);

create table qbo.dim_vendor (
     vendor_key       integer        generated always as identity primary key
    ,qbo_id           varchar(20)    not null unique
    ,display_name     varchar(200)
    ,is_active        boolean
);

create table qbo.dim_class (
     class_key        integer        generated always as identity primary key
    ,qbo_id           varchar(20)    not null unique
    ,class_name       varchar(120)
);

create table qbo.dim_date (
     date_key         integer        primary key   -- yyyymmdd
    ,d                date           not null unique
    ,y                integer
    ,q                varchar(2)
    ,m                integer
    ,month_name       varchar(12)
    ,year_month       varchar(7)
    ,fiscal_year      integer                      -- from dbt var fy_start (default 1)
    ,fiscal_period    integer
    ,week_start       date
    ,is_month_end     boolean
);

grant select, insert, update
    on qbo.dim_account
      ,qbo.dim_customer
      ,qbo.dim_vendor
      ,qbo.dim_class
      ,qbo.dim_date
    to qbo_etl;
