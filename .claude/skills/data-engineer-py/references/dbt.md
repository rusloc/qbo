# dbt

Everything in-warehouse transformation. Load for any dbt question. If the target is **Microsoft Fabric Warehouse**, stop and use the `dbt-fabric-warehouse` skill instead — it has dialect rules this file does not.

## Contents
1. Which dbt: Core 1.x vs Fusion 2.x
2. Project conventions
3. Sources, staging, marts
4. Materializations and incremental strategies (incl. microbatch)
5. Snapshots (SCD2) and seeds
6. Tests, unit tests, contracts, versions
7. Macros, packages, Python models
8. Running dbt: CLI, selection, environments, CI
9. Running dbt from Python and from Airflow
10. Pitfalls

---

## 1. Which dbt

| | dbt Core 1.x | dbt Fusion engine 2.x |
|---|---|---|
| Implementation | Python package (`dbt-core` + `dbt-<adapter>`), latest 1.12.x (Sep 2026) | Rust binary `dbt` (2.0.0-rc as of Sep 2026); "v2 is the current generation" per dbt docs |
| Install | `uv add "dbt-core>=1.10,<2" dbt-postgres` (or dbt-snowflake/-bigquery/-databricks/-duckdb/-redshift/-fabric) | `curl -fsSL https://public.cdn.getdbt.com/fs/install/install.sh \| sh` / `brew install dbt` (official tap) / winget; VS Code extension |
| Strengths | Every adapter, Python models, mature packages, `dbtRunner` in-process | Much faster parse/compile, static SQL analysis (catches errors before running), `dbt --version` shows `dbt Fusion 2.x` |
| Gaps | Slower on large projects | Adapter coverage still growing; Python models and some Jinja edge cases unsupported; check release notes before migrating |

Decision rule: **match the installed engine** (`dbt --version`). Default new projects to Core 1.x when the adapter is niche or Python models are needed; Fusion when the warehouse is Snowflake/Databricks/BigQuery/Redshift/Postgres/DuckDB and the team wants speed and static checks. Model SQL, YAML and project structure are the same for both, so everything below applies to both unless marked.

Never assume dbt Cloud (the dbt platform); ask if you see `dbt_cloud` references or no `profiles.yml`.

---

## 2. Project conventions

```
dbt/
├── dbt_project.yml
├── packages.yml            # dbt_utils, dbt_expectations, ...
├── profiles.yml.example    # real profiles.yml stays out of git (~/.dbt or DBT_PROFILES_DIR)
├── models/
│   ├── staging/<source>/   # stg_<source>__<object>.sql + _<source>__sources.yml + _<source>__models.yml
│   ├── intermediate/       # int_<entity>__<verb>.sql
│   └── marts/<domain>/     # fct_*, dim_*, agg_* + _<domain>__models.yml
├── snapshots/              # YAML-defined (1.9+) or .sql
├── seeds/                  # tiny static mappings only
├── macros/
├── tests/                  # singular tests
└── analyses/
```

`dbt_project.yml` essentials:
```yaml
name: acme
version: "1.0.0"
profile: acme
model-paths: ["models"]
models:
  acme:
    +persist_docs: {relation: true, columns: true}
    staging:      {+materialized: view,  +schema: staging}
    intermediate: {+materialized: view,  +schema: intermediate}
    marts:        {+materialized: table, +schema: marts}
vars:
  start_date: "2024-01-01"
flags:
  require_explicit_package_overrides_for_builtin_materializations: true
```

Model SQL shape (every model):
```sql
{{ config(materialized='incremental', unique_key='order_id', incremental_strategy='merge') }}

with orders as (
    select * from {{ ref('stg_shop__orders') }}
    {% if is_incremental() %}
    where updated_at > (select coalesce(max(updated_at), '1900-01-01') from {{ this }})
    {% endif %}
),

final as (
    select ...
    from orders
)

select * from final
```
One model = one grain = one responsibility. `source()` only in staging; `ref()` everywhere else. Naming: `stg_`, `int_`, `fct_`, `dim_`, `agg_`; columns snake_case; keys end in `_id`; booleans start `is_`/`has_`; timestamps end `_at`, dates `_date`.

---

## 3. Sources, staging, marts

**Sources YAML** (one per source system):
```yaml
version: 2
sources:
  - name: shop
    database: raw            # or env_var('DBT_RAW_DB')
    schema: fivetran_shop    # raw schema loaded by Fivetran/Airbyte/ADF/Python
    loaded_at_field: _fivetran_synced   # _airbyte_extracted_at / _loaded_at
    freshness: {warn_after: {count: 6, period: hour}, error_after: {count: 24, period: hour}}
    tables:
      - name: orders
        columns:
          - {name: id, tests: [unique, not_null]}
```
**Staging**: explicit column list, rename, cast, dedupe when raw is append/CDC:
```sql
with src as (select * from {{ source('shop', 'orders') }}),
deduped as (
    select *, row_number() over (partition by id order by _extracted_at desc) as rn from src
),
final as (
    select
        id                                  as order_id,
        cast(customer_id as bigint)         as customer_id,
        cast(total_amount as decimal(18,2)) as total_amount,
        cast(created_at as timestamp)       as created_at,
        coalesce(_deleted, false)           as is_deleted
    from deduped
    where rn = 1
)
select * from final
```
Handle tool system columns here: Fivetran `_fivetran_deleted`/`_fivetran_synced`, Airbyte `_airbyte_extracted_at`/`_airbyte_meta`, CDC `op`/`lsn`.

**Marts**: facts at event grain with FK columns, dims with surrogate keys (`{{ dbt_utils.generate_surrogate_key(['source', 'natural_id']) }}`), aggregates only when BI needs pre-computed grain.

---

## 4. Materializations and incremental strategies

| Materialization | Use |
|---|---|
| `view` | staging, cheap intermediates |
| `table` | dims, small/medium marts rebuilt fully |
| `incremental` | large facts/event tables |
| `ephemeral` | tiny CTE-like helpers (avoid on adapters that inline badly, e.g. Fabric) |
| `materialized_view` / `dynamic_table` | when the warehouse maintains refresh natively (Snowflake dynamic tables, BigQuery/PG MVs) |

Incremental strategies (adapter support varies — check the adapter docs):
- `append` — immutable events, no dedupe.
- `merge` (default on most warehouses) — needs `unique_key`; `merge_update_columns`/`merge_exclude_columns` to limit updates; `incremental_predicates` to prune the target scan (`["DBT_INTERNAL_DEST.event_date >= dateadd(day, -7, current_date)"]`).
- `delete+insert` — Postgres/Redshift/Snowflake; when merge is slow or keys aren't unique per batch.
- `insert_overwrite` — BigQuery/Spark/Databricks partition replacement; requires `partition_by`.
- `microbatch` (dbt ≥1.9) — time-sliced processing with per-batch retry/backfill. Use for large event tables where "replace the day" is the natural unit:
  ```sql
  {{ config(materialized='incremental', incremental_strategy='microbatch',
            event_time='event_ts', begin='2024-01-01', batch_size='day', lookback=3) }}
  select ... from {{ ref('stg_events') }}   -- upstream must also declare event_time so the batch filter applies
  ```
  Backfill a range: `dbt run -s fct_events --event-time-start "2025-03-01" --event-time-end "2025-03-08"`. Failed batches: `dbt retry`.
- `on_schema_change`: `append_new_columns` for additive drift; `fail` when contracts matter; default `ignore` silently drops new columns — don't leave it default on important models.
- First run / `--full-refresh` rebuilds the table; guard expensive full refreshes in prod with `full_refresh: false` in config where appropriate.

---

## 5. Snapshots and seeds

YAML snapshots (dbt ≥1.9, preferred):
```yaml
snapshots:
  - name: snap_customers
    relation: source('crm', 'customers')
    config:
      schema: snapshots
      unique_key: id
      strategy: timestamp        # or check + check_cols: [status, plan]
      updated_at: updated_at
      dbt_valid_to_current: "cast('9999-12-31' as date)"   # instead of null for current rows
      hard_deletes: new_record   # ignore | invalidate | new_record
```
- Snapshots run on the schedule that matches the source's change frequency (`dbt snapshot` in the same job as staging, before marts).
- Never snapshot a model with `select *` from a view whose columns change; snapshot the source or an explicit-column staging model.
- Seeds: static mappings under ~1k rows (country codes, status labels). Not for data loading. Set `column_types` explicitly.

---

## 6. Tests, unit tests, contracts, versions

Generic data tests on every mart key and FK:
```yaml
models:
  - name: fct_orders
    config: {contract: {enforced: true}}
    columns:
      - {name: order_id, data_type: bigint, tests: [unique, not_null]}
      - name: customer_id
        data_type: bigint
        tests:
          - relationships: {to: ref('dim_customers'), field: customer_id, config: {severity: warn}}
      - {name: status, tests: [{accepted_values: {values: [placed, shipped, cancelled]}}]}
```
- Singular tests (`tests/assert_*.sql`) for business rules ("no negative revenue after refunds").
- `dbt_expectations` (`expect_column_values_to_be_between`, `expect_table_row_count_to_be_between`) for statistical checks; `dbt_utils` (`unique_combination_of_columns`, `accepted_range`, `recency`).
- **Unit tests** (dbt ≥1.8) for logic, with fixture rows and no warehouse data dependency:
  ```yaml
  unit_tests:
    - name: fct_orders_net_amount
      model: fct_orders
      given:
        - input: ref('stg_shop__orders')
          rows: [{order_id: 1, total_amount: 100, discount: 10}]
        - input: ref('stg_shop__refunds')
          rows: []
      expect:
        rows: [{order_id: 1, net_amount: 90}]
  ```
  Run: `dbt test --select "test_type:unit"` (in CI, on every PR; they run against an empty model build).
- **Contracts** freeze column names/types on marts; **versions** (`versions: [{v: 2, columns: ...}]`) for breaking changes with `latest_version`.
- Severity and thresholds: `config: {severity: warn, warn_if: ">0", error_if: ">100"}`; `store_failures: true` for debugging.

---

## 7. Macros, packages, Python models

- Packages (`packages.yml` → `dbt deps`): `dbt-labs/dbt_utils`, `metaplane/dbt_expectations`, `dbt-labs/codegen` (generate staging models/YAML: `dbt run-operation generate_source --args '{schema_name: fivetran_shop}'`), `dbt-labs/dbt_project_evaluator` (conventions linter), `elementary-data/elementary` (observability), `dbt-labs/audit_helper` (compare model versions), `calogica/dbt_date`.
- Macros: for repeated SQL patterns (`cents_to_dollars`, surrogate keys, standard `_loaded_at` handling); keep them small and adapter-aware (`{{ adapter.dispatch(...) }}` when supporting multiple warehouses). Custom `generate_schema_name` so dev schemas prefix with the user and prod uses the plain custom schema.
- `on-run-end` hooks for grants: `+grants: {select: ['reporter']}` is the modern way.
- **Python models** (`models/.../my_model.py`, dbt Core only; Snowflake/Databricks/BigQuery/DuckDB):
  ```python
  def model(dbt, session):
      dbt.config(materialized="table", packages=["scikit-learn"])
      df = dbt.ref("fct_orders").to_pandas()   # Snowpark on Snowflake; Spark DataFrame on Databricks
      ...
      return df
  ```
  Use only when SQL can't do it (ML scoring, complex parsing); they run on the warehouse's Python runtime, not your laptop.

---

## 8. Running dbt: CLI, selection, environments, CI

Daily commands:
```bash
dbt deps                                   # after packages.yml changes
dbt debug                                  # connection + profile sanity
dbt parse                                  # fast validation of project + YAML (use in pre-commit)
dbt build -s +fct_orders                   # run + test + snapshot + seed, model and its ancestors
dbt build -s stg_shop__orders+ --exclude tag:slow
dbt source freshness
dbt run -s state:modified+ --defer --state prod-artifacts/   # slim CI: only changed models, read unchanged from prod
dbt run --full-refresh -s fct_orders
dbt retry                                  # re-run only what failed in the last invocation
dbt docs generate && dbt docs serve
dbt compile -s model && cat target/compiled/...   # inspect rendered SQL when debugging
```
Selection: `+model+` (ancestors/descendants), `tag:daily`, `path:models/marts`, `source:shop+`, `resource_type:snapshot`, `@model` (model + descendants + their ancestors).

Environments: `profiles.yml` targets `dev`/`ci`/`prod` with `env_var()` for credentials; `DBT_PROFILES_DIR` and `DBT_TARGET` in CI/Airflow; dev writes to `dev_<user>` schemas via `generate_schema_name`.

Local/CI without a warehouse: `dbt-duckdb` target reading Parquet fixtures or seeds — runs the whole project in seconds. Use it for unit tests and PR checks; run slim CI against the real warehouse for adapter-specific SQL.

CI pipeline (GitHub Actions): `uv sync` → `dbt deps` → `dbt parse` → `sqlfluff lint` (templater `dbt`) → `dbt build -s state:modified+ --defer --state ./prod-artifacts` (download `manifest.json` from the last prod run as an artifact) → upload `target/` artifacts. Prod: scheduled from Airflow (§9), never from a laptop.

---

## 9. Running dbt from Python and from Airflow

**In-process (dbt Core only):**
```python
from dbt.cli.main import dbtRunner, dbtRunnerResult

res: dbtRunnerResult = dbtRunner().invoke(["build", "--select", "tag:daily", "--target", "prod"])
if not res.success:
    raise RuntimeError(res.exception or "dbt build failed")
for r in res.result:                       # RunExecutionResult
    print(r.node.name, r.status, r.execution_time)
```
Use `subprocess.run(["dbt", ...], check=True)` for Fusion or when isolating dependencies; parse `target/run_results.json` afterwards for per-model status.

**Airflow — pick one:**
1. **Astronomer Cosmos** (`astronomer-cosmos`, ≥1.10 for Airflow 3 — verify the compatibility matrix): renders each model/test as its own task with per-model retries and lineage.
   ```python
   from cosmos import DbtDag, ProjectConfig, ProfileConfig, ExecutionConfig, RenderConfig
   from cosmos.profiles import PostgresUserPasswordProfileMapping

   dbt_dag = DbtDag(
       dag_id="dbt_daily",
       schedule="0 5 * * *",
       project_config=ProjectConfig("/opt/airflow/dbt"),
       profile_config=ProfileConfig(
           profile_name="acme", target_name="prod",
           profile_mapping=PostgresUserPasswordProfileMapping(conn_id="warehouse", profile_args={"schema": "marts"}),
       ),
       execution_config=ExecutionConfig(dbt_executable_path="/opt/airflow/dbt_venv/bin/dbt"),
       render_config=RenderConfig(select=["tag:daily"]),
       default_args={"retries": 2},
   )
   ```
   `DbtTaskGroup` embeds the same into a larger DAG after ingestion tasks. Keep dbt in its own venv (`dbt_executable_path`) — dbt and Airflow pin conflicting deps.
2. **One BashOperator/`@task.bash` per job** (`dbt build -s tag:daily`) — simplest, coarse retries, fine for small projects. Parse `run_results.json` in a downstream task to surface failures.
3. **dbt Cloud provider** (`apache-airflow-providers-dbt-cloud`, `DbtCloudRunJobOperator`) only when the org uses the dbt platform.

Order in a DAG: ingestion (Fivetran/Airbyte/ADF/Python) → `dbt source freshness` (optional gate) → `dbt build` → downstream consumers (reverse ETL, ML). Trigger via Airflow **assets** so dbt runs when raw data lands rather than on a fixed clock (see `airflow.md` §4).

---

## 10. Pitfalls

- Incremental filter on `{{ this }}` without `coalesce` fails on the first run of an empty table; `max()` over a huge target is slow — filter with `incremental_predicates` or a watermark model.
- `is_incremental()` is false during `--full-refresh` and on the first run — make sure the full path is also correct and affordable.
- Tests on views over raw tables can be slow and expensive; test staging outputs, not raw sources, except for keys/freshness.
- `unique_key` as a list is supported for merge on most adapters; ensure it's actually unique in the batch, else merge throws or double-updates.
- Snapshot `check` strategy with `select *` breaks when columns change; list `check_cols`.
- Don't put credentials in `dbt_project.yml` or `vars`; use `env_var()` in `profiles.yml`.
- Fusion: run `dbt parse`/`dbt compile` — its static analysis reports SQL errors Core would only find at runtime; migrate one project at a time and diff `target/` artifacts.
- Fabric Warehouse: use the `dbt-fabric-warehouse` skill — no `ephemeral`, no nested CTEs, `TOP` not `LIMIT`, binary collation, `varchar` not `nvarchar`.
