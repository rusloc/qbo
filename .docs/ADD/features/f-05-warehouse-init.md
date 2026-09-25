> **DRAFT — projection state.** Migration plan for review. Nothing here has been applied to `vosk.dev` yet. There is no local database: each migration is applied straight to `vosk.dev`, one at a time, after USER approval, and verified there (USER 2026-09-25).

# F-05 · Warehouse init — migration plan (schema `qbo`)

- **Spec:** §2 (schema), §2.4 (serve layer) · **ADRs:** ADR-0002 (dbt vs migrations), ADR-0003 (schema `qbo`, roles, apply path), ADR-0007 (token vault), ADR-0008 (shared project)
- **Lane:** Warehouse

## Boundary: migrations vs dbt

| Object | Created by | Filled by |
|---|---|---|
| schema `qbo`, roles `qbo_etl` / `qbo_reader`, grants | migration | — |
| `raw_entity`, `sync_state`, `qa_reports_snapshot` | migration | Python (`qbo_sync`, validation) |
| `dim_account`, `dim_customer`, `dim_vendor`, `dim_class`, `dim_date` | migration | dbt (incremental `merge`) |
| `fact_gl` | migration | dbt (incremental `delete+insert` per transaction) |
| `fact_budget` | migration | open: budget source (spec issue 3) |
| `stg_*` views | dbt | — |
| `vw_fact_gl`, `vw_dim_account`, `vw_dim_date`, `vw_dim_class`, `vw_fact_budget` | dbt (`grants: select → qbo_reader`) | — |
| token functions (ADR-0007) | migration M5 | — |

## Migrations

Files: `supabase/migrations/<yyyymmddhhmmss>_qbo_<name>.sql`. Each is applied with MCP `apply_migration` under the same name, after USER approval (ADR-0003).

| # | Name | Content |
|---|---|---|
| M1 | `qbo_init_schema_and_roles` | schema, 2 roles, schema grants |
| M2 | `qbo_raw_and_control` | `raw_entity`, `sync_state`, `qa_reports_snapshot` + grants |
| M3 | `qbo_dimensions` | 5 dimension tables + grants |
| M4 | `qbo_facts` | `fact_gl`, `fact_budget` + grants |
| M5 | `qbo_token_vault` | Vault token functions (ADR-0007) |

### M1 · `qbo_init_schema_and_roles`

```sql
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
```

No `revoke` is needed: a new schema grants nothing to `PUBLIC`, `anon` or `authenticated`, and `vosk.dev` has no database-wide default privileges (checked 2026-09-25).

### M2 · `qbo_raw_and_control`

```sql
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
```

### M3 · `qbo_dimensions`

```sql
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
```

### M4 · `qbo_facts`

```sql
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
```

### M5 · `qbo_token_vault`

ADR-0007 is accepted; the SQL is written together with the M1–M4 files. Signatures:
- `qbo.refresh_token_lock() returns text`: locks and returns `qbo_refresh_token`
- `qbo.refresh_token_store(p_token text) returns void`: rotates it

Both are `security definer`, owned by `postgres`, with `set search_path = ''` and `execute` granted to `qbo_etl` only.

### USER step after M1 (outside the repo, Supabase SQL editor)

```sql
alter role qbo_etl    with login password '<from password manager>';
alter role qbo_reader with login password '<from password manager>';
```

Connection user through the session pooler: `qbo_etl.<project-ref>` / `qbo_reader.<project-ref>`.

## Changes vs spec §2 (need USER approval)

| Change | Why |
|---|---|
| `TIMESTAMP` → `timestamptz`; `DECIMAL` → `numeric(15,2)`; `JSONB/NVARCHAR` → `jsonb` | CLAUDE.md types; Postgres only (ADR-0001) |
| `qbo_id not null` on `dim_customer`, `dim_vendor`, `dim_class` | dbt merges on `qbo_id`; a null would duplicate members |
| `fact_gl`: `txn_type`, `txn_qbo_id`, `line_num` `not null` | the unique key would accept duplicate rows that contain nulls |
| `is_voided` / `is_deleted` `not null` | `vw_fact_gl` filters `= false`; a null row would vanish silently |
| `dim_date.d not null unique` | V1 joins facts on `d` |
| `fact_budget`: surrogate `budget_key` + `unique nulls not distinct`; FK on `class_key`; `amount not null` | spec issue 1: the spec's PK includes the nullable `class_key`, which Postgres rejects |

**Suggested, not included (your call):** a `check` constraint on `stmt_section` values (`Revenue`, `COGS`, `OpEx`, `OtherInc`, `OtherExp`, `Tax`). A typo in the consultant mapping would otherwise drop rows from the DAX measures without an error.

## dbt fill pattern (ADR-0002)

```yaml
# dbt/dbt_project.yml (excerpt)
models:
  qbo_pnl:
    staging:
      +materialized: view                        # stg_*
    serve:
      +materialized: view                        # vw_*
      +grants:
        select: ['qbo_reader']
    marts:                                       # dim_* / fact_* tables created by migrations
      +materialized: incremental
      +full_refresh: false                       # never drop or recreate a migration-owned table
      +on_schema_change: append_new_columns      # insert only the model's columns; identity keys stay DB-generated
```

## Open items

1. USER approval of the changes vs spec §2 and of the `stmt_section` check.
2. Budget source for real clients (spec issue 3). `fact_budget` is created empty.
3. Staging shapes (spec issue 2): `stg_*` are dbt views over `raw_entity`. Recommendation: Track C writes QBO-shaped JSON into `raw_entity`, so demo data runs through the same pipeline.
4. `FY_START` lives in two places (dbt var for `dim_date`, Power BI parameter). Settle in Phase 4 together with the `TOTALYTD` issue.

## Verification after apply (read-only)

- `list_tables` on schema `qbo`: 10 tables, owner `postgres`
- grants per role from `information_schema.role_table_grants` match the tables above; `anon` and `authenticated` have none
- `get_advisors` security: no new findings for `qbo`; performance: only the accepted INFO notices (ADR-0003)

Rollback, only if a migration leaves `qbo` half-built (destructive; the USER runs it):

```sql
drop schema qbo cascade;
drop role qbo_etl;
drop role qbo_reader;
```
