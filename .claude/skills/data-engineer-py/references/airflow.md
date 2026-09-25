# Apache Airflow 3

Orchestration for everything in this stack. **Target Airflow 3.x** (3.0 Apr 2025; 3.3 current in Sep 2026; 2.x reached end-of-life Apr 2026). Much older training material describes 2.x — the import paths, context variables and scheduling API changed. When the user's installed version is unknown, ask or check `airflow version`; write 3.x code and note it.

## Contents
1. Runtime model and install
2. DAG authoring rules
3. Task patterns (TaskFlow, operators, sensors, deferrables, isolation)
4. Assets and data-aware scheduling
5. Connections, variables, secrets, config
6. Dynamic task mapping, task groups, branching
7. Testing DAGs
8. Deployment and CI
9. Migrating 2 → 3 checklist
10. Common failure modes

---

## 1. Runtime model and install

Components (3.x): `api-server` (UI + REST API v2), `scheduler`, `dag-processor` (separate process, mandatory), `triggerer` (for deferrables), workers (`celery worker` / `edge worker` / Kubernetes pods). Tasks run through the **Task SDK** and talk to the API server — they have **no direct metadata-DB access** (this is why many 2.x snippets break).

Executors: `LocalExecutor` for dev/small, `CeleryExecutor` or `KubernetesExecutor` for prod, `EdgeExecutor` for remote/on-prem workers; multiple executors may be configured together.

Install — always with the constraints file for the exact Airflow + Python version:
```bash
AIRFLOW_VERSION=3.3.1; PY=3.12
uv pip install "apache-airflow[postgres,celery]==${AIRFLOW_VERSION}" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PY}.txt"
uv pip install apache-airflow-providers-standard apache-airflow-providers-common-sql \
  apache-airflow-providers-postgres   # + fivetran/airbyte/microsoft-azure/… as needed
airflow standalone      # dev: api-server + scheduler + dag-processor + triggerer + LocalExecutor, SQLite
```
Local dev alternatives: **Astro CLI** (`astro dev init && astro dev start`, Postgres + all components in Docker, mirrors prod best) or the official `docker-compose.yaml` for 3.x. Keep the pipeline package (`src/`) installed into the same image (`uv pip install -e .`).

---

## 2. DAG authoring rules

```python
# dags/orders_daily.py
from datetime import datetime, timedelta
from airflow.sdk import dag, task, Asset

orders_raw = Asset("s3://acme-landing/orders")          # what this DAG produces

@dag(
    dag_id="orders_daily",
    schedule="0 3 * * *",                               # cron | timedelta | Timetable | [Asset, ...] | None
    start_date=datetime(2025, 1, 1),
    catchup=False,                                      # default in 3.x; set True only for deliberate backfilling DAGs
    max_active_runs=1,
    default_args={
        "owner": "data-eng", "retries": 3, "retry_delay": timedelta(minutes=5),
        "retry_exponential_backoff": True, "execution_timeout": timedelta(hours=1),
    },
    tags=["ingestion", "orders"],
    doc_md=__doc__,
)
def orders_daily():
    @task(outlets=[orders_raw])
    def extract_load(data_interval_start=None, data_interval_end=None, run_id=None) -> dict:
        from acme_pipelines.pipelines.orders import run          # import inside the task: keeps parse fast, deps isolated
        from acme_pipelines.config import Settings
        result = run(data_interval_start, data_interval_end, Settings())
        return {"rows": result.rows_loaded, "watermark": result.max_watermark.isoformat()}

    extract_load()

orders_daily()
```
Rules and why:
- **Top-level code is parsed every ~30 s by the dag-processor.** No DB queries, API calls, `Variable.get()` or heavy imports at module level; do them inside tasks. Module-level `Variable.get` also silently makes every parse hit the API.
- **Thin DAGs, fat package.** The task calls `run(start, end, settings)` from `src/` (see `python-stack.md` §3). The DAG only wires intervals, retries and dependencies.
- **Interval, not clock.** Use `data_interval_start`/`data_interval_end` (context keys or `{{ data_interval_start }}` templates). `logical_date` can be `None` for manually triggered runs in 3.x; `execution_date`, `prev_ds`, `next_ds`, `yesterday_ds` no longer exist.
- `schedule=` is the only scheduling argument (`schedule_interval`/`timetable` removed). Default is `None` (manual only).
- `start_date` static and in the past; `catchup=False` unless the DAG is designed for backfill; backfills are explicit: `airflow backfill create --dag-id orders_daily --from-date 2025-01-01 --to-date 2025-01-31`.
- One DAG per pipeline/cadence; `max_active_runs=1` for anything that merges into a warehouse; `depends_on_past=True` only when a run truly needs the previous one.
- `dag_id` = file name = snake_case; always `owner`, `tags`, `doc_md`.
- Idempotent tasks: same interval → same result. If a task can't be made idempotent, it must not have retries.

---

## 3. Task patterns

- **TaskFlow (`@task`) by default**; classic operators when a provider gives you one (`SQLExecuteQueryOperator`, `FivetranOperator`, `AirbyteTriggerSyncOperator`, `AzureDataFactoryRunPipelineOperator`). Core operators now live in `apache-airflow-providers-standard` (`airflow.providers.standard.operators.python.PythonOperator`, `...operators.bash.BashOperator`, `...operators.empty.EmptyOperator`, `...operators.trigger_dagrun.TriggerDagRunOperator`, `...sensors.*`).
- `@task.bash` for shell commands (returns the command string), `@task.branch`, `@task.short_circuit`, `@task.sensor`.
- **Dependency isolation**: `@task.virtualenv(requirements=[...], system_site_packages=False)` (builds per run — slow), `@task.external_python(python="/opt/venvs/dbt/bin/python")` (pre-built venv in the image — preferred), `@task.kubernetes`/`@task.docker` for full isolation. This is how dbt, heavy ML deps, or conflicting library versions coexist with Airflow.
- **XCom is for small metadata** (counts, paths, watermarks). Never a dataframe. For larger payloads set the object-storage XCom backend: `AIRFLOW__CORE__XCOM_BACKEND=airflow.providers.common.io.xcom.backend.XComObjectStorageBackend`, `AIRFLOW__COMMON_IO__XCOM_OBJECTSTORAGE_PATH=s3://acme-airflow/xcom`, `..._THRESHOLD=<bytes>`.
- **Sensors**: `mode="reschedule"` (frees the worker slot) with `poke_interval`/`timeout`; better, `deferrable=True` on any operator/sensor that supports it (most cloud providers do) — the task waits in the triggerer, not on a worker. Prefer asset-driven scheduling (§4) over `ExternalTaskSensor` chains.
- **Object storage** without boto/adlfs boilerplate: `from airflow.sdk import ObjectStoragePath; p = ObjectStoragePath("s3://bucket/path", conn_id="aws_default"); p.write_bytes(...)`.
- **SQL**: `SQLExecuteQueryOperator(conn_id="warehouse", sql="...")` from `common-sql` for DDL/DML; hooks (`PostgresHook(...).get_conn()`) only inside tasks; bulk data still goes through the warehouse bulk path (see `python-stack.md` §5).
- Callbacks: `on_failure_callback` / `on_success_callback` at DAG or task level for alerting (Slack provider `SlackNotifier`, or a small function posting to a webhook). `sla` was removed in 3.0; use **deadline alerts** (3.1+, `deadline=DeadlineAlert(...)`) or a freshness DAG.
- Pools (`pool="source_db"`) to cap concurrency against a fragile source; `priority_weight` for critical paths; `max_active_tis_per_dag` on mapped tasks.

---

## 4. Assets and data-aware scheduling

Assets (renamed from Datasets in 3.0) turn "run dbt after ingestion" into a declared dependency instead of a fixed clock or cross-DAG sensors.

```python
from airflow.sdk import Asset, AssetAlias, asset, dag, task

raw_orders    = Asset(name="raw_orders",    uri="snowflake://raw/shop/orders")
raw_customers = Asset(name="raw_customers", uri="snowflake://raw/shop/customers")

@task(outlets=[raw_orders])                       # producing task marks the asset updated on success
def load_orders(): ...

@dag(schedule=(raw_orders & raw_customers), start_date=datetime(2025,1,1))   # run when BOTH updated since last run
def dbt_marts(): ...

@dag(schedule=[raw_orders])                       # list == all-of; use `raw_orders | raw_customers` for any-of
def notify(): ...

@asset(schedule="@hourly", uri="s3://acme-landing/events")   # 3.0+: a one-task DAG that produces one asset
def events_raw():
    ...
```
- Producers attach extra info: `from airflow.sdk import Metadata; yield Metadata(raw_orders, {"rows": 1234})`; consumers read `inlet_events[raw_orders]`.
- `AssetAlias` when the concrete URI is only known at runtime (per-partition paths).
- Event-driven: `AssetWatcher` + a message-queue trigger (SQS/Kafka via `apache-airflow-providers-common-messaging`, 3.1+) schedules a DAG when a message arrives — the pattern for "file landed → process".
- Assets are matched by `name`/`uri` across DAGs; define them once in `src/acme_pipelines/assets.py` and import in every DAG.
- Combine time and data: `schedule=AssetOrTimeSchedule(timetable=CronTriggerTimetable("0 6 * * *", timezone="UTC"), assets=[raw_orders])` — run on data arrival but at least daily.

---

## 5. Connections, variables, secrets, config

- Connections: `AIRFLOW_CONN_WAREHOUSE='postgresql://user:pass@host:5432/db'` (URI or JSON), the UI, or a secrets backend. In tasks: `from airflow.sdk import Connection; conn = Connection.get("warehouse")` or a hook.
- Variables: `from airflow.sdk import Variable; Variable.get("lookback_minutes", default=30)` — inside tasks only; JSON variables via `deserialize_json=True`. Not for secrets.
- Secrets backend (prod): `AIRFLOW__SECRETS__BACKEND=airflow.providers.hashicorp.secrets.vault.VaultBackend` / `airflow.providers.amazon.aws.secrets.secrets_manager.SecretsManagerBackend` / `airflow.providers.microsoft.azure.secrets.key_vault.AzureKeyVaultBackend` / `airflow.providers.google.cloud.secret_manager...`, with `AIRFLOW__SECRETS__BACKEND_KWARGS` for prefixes. Connections and variables then resolve from the store by name.
- All config via `AIRFLOW__SECTION__KEY` env vars in the image/Helm values; never edit `airflow.cfg` by hand in prod. Common: `AIRFLOW__CORE__EXECUTOR`, `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`, `AIRFLOW__CORE__PARALLELISM`, `AIRFLOW__SCHEDULER__DAG_DIR_LIST_INTERVAL`, `AIRFLOW__CORE__DEFAULT_TIMEZONE`, `AIRFLOW__API__AUTH_BACKENDS`.
- DAG bundles (3.0+): `[dag_processor] dag_bundle_config_list` with `LocalDagBundle` (mounted folder) or `GitDagBundle` (pull DAGs from a repo, versioned per run); DAG versioning shows which code a run used.
- Pass Airflow-resolved values into the package's `Settings` explicitly at the task boundary; library code stays Airflow-free.

---

## 6. Dynamic task mapping, task groups, branching

```python
@task
def list_partitions(data_interval_start=None, data_interval_end=None) -> list[dict]:
    return [{"table": t, "start": data_interval_start.isoformat(), "end": data_interval_end.isoformat()}
            for t in ("orders", "customers", "products")]

@task(max_active_tis_per_dag=4, map_index_template="{{ task.op_kwargs['table'] }}")
def load(table: str, start: str, end: str) -> int: ...

@task
def summarize(counts: list[int]) -> int: return sum(counts)

summarize(load.expand_kwargs(list_partitions()))
```
- `.expand(x=[...])` for one mapped arg, `.partial(fixed=1).expand(x=...)`, `.expand_kwargs(list_of_dicts)` for several. Mapped output is a lazy list; reduce with a downstream task.
- Map over a *task's* output (computed at run time) so partition lists come from the source/control table, not from DAG code.
- Cap fan-out (`max_map_length` default 1024) and concurrency (`max_active_tis_per_dag`, pools).
- `TaskGroup` (from `airflow.sdk`) for visual grouping and reuse; `SubDagOperator` no longer exists.
- Branching: `@task.branch` returns task_id(s) to follow; join with `trigger_rule="none_failed_min_one_success"`. `@task.short_circuit` to skip the rest when there's nothing to do (e.g. zero new rows).
- Cross-DAG: prefer assets; `TriggerDagRunOperator(wait_for_completion=True, deferrable=True)` when you need explicit fan-out to another DAG with params.

---

## 7. Testing DAGs

Three layers, all in `tests/`:

```python
# tests/test_dag_integrity.py — catches import errors, cycles, missing defaults (runs in CI, no DB needed)
from pathlib import Path
from airflow.models.dagbag import DagBag

def test_no_import_errors():
    bag = DagBag(dag_folder=str(Path(__file__).parents[1] / "dags"), include_examples=False)
    assert bag.import_errors == {}
    for dag in bag.dags.values():
        assert dag.tags, f"{dag.dag_id} has no tags"
        assert all(t.retries >= 1 for t in dag.tasks), f"{dag.dag_id} has tasks without retries"
```
```python
# tests/test_orders_daily.py — run the DAG in-process (needs `airflow db migrate` once; SQLite is fine)
from dags.orders_daily import orders_daily

def test_dag_runs(monkeypatch):
    monkeypatch.setattr("acme_pipelines.pipelines.orders.run", lambda s, e, cfg: FakeResult(rows_loaded=3))
    run = orders_daily().test(run_conf={})
    assert run.state == "success"
```
- Unit-test the *package* functions directly; the DAG test only proves wiring.
- CLI equivalents: `airflow dags list-import-errors`, `airflow dags test orders_daily 2025-01-01`, `airflow tasks test orders_daily extract_load 2025-01-01`.
- Lint: `ruff check --select AIR --preview dags/` flags removed 2.x APIs and bad practices (top-level code, missing `start_date`).
- `pytest` fixtures set `AIRFLOW_HOME=$(mktemp -d)` and `AIRFLOW__CORE__LOAD_EXAMPLES=False`; run `airflow db migrate` in `conftest.py` if `dag.test()` is used.

---

## 8. Deployment and CI

- **Immutable image** per release: base `apache/airflow:3.x-python3.12` (or Astro Runtime), `uv pip install` providers + `src/` with constraints, `dags/` copied in or delivered via `GitDagBundle`. Separate venvs for dbt/heavy deps (`/opt/venvs/<name>`) referenced by `@task.external_python`.
- CI on every PR: `ruff`, `mypy`, `pytest` (integrity test at minimum), `uv lock --check`, build image, optionally `airflow dags test` for critical DAGs.
- CD: push image → rolling update (Helm chart `apache-airflow/airflow`, or managed: Astro, MWAA, Cloud Composer, Fabric Apache Airflow Job). DAG-only changes via bundle refresh; dependency changes always rebuild the image.
- Observability: OpenLineage provider (`apache-airflow-providers-openlineage`) → Marquez/DataHub/Atlan; StatsD/OTel metrics (`AIRFLOW__METRICS__OTEL_ON=True`); log shipping to object storage (`AIRFLOW__LOGGING__REMOTE_LOGGING=True`).
- Metadata DB: PostgreSQL, backed up; `airflow db clean --clean-before-timestamp` on a schedule to keep it small.

---

## 9. Migrating 2 → 3 checklist

1. Be on 2.11 first (`airflow config lint`, `ruff --select AIR --preview` to list incompatibilities).
2. Imports: `airflow.decorators` → `airflow.sdk`; `airflow.datasets.Dataset` → `airflow.sdk.Asset`; `airflow.models.Variable/Connection` inside tasks → `airflow.sdk.Variable/Connection`; `airflow.operators.python/bash/empty`, `airflow.sensors.*` → `airflow.providers.standard.*`; `airflow.contrib.*` gone.
3. DAG args: `schedule_interval`/`timetable` → `schedule`; remove `sla`; `SubDagOperator` → `TaskGroup`; `catchup` now defaults to `False`.
4. Context: `execution_date`, `prev_*`, `next_*`, `yesterday_ds`, `tomorrow_ds`, `conf` removed → `logical_date` (may be `None`), `data_interval_start/end`, `run_id`, `dag_run.conf`.
5. No direct DB access from tasks (`settings.Session`, `airflow.models.TaskInstance` queries) → REST API v2 or SDK objects.
6. Deployment: `airflow webserver` → `airflow api-server`; run `airflow dag-processor` separately; REST API moves to `/api/v2`; Python ≥ 3.10.
7. `airflow db migrate` on the new version; re-verify secrets backend and executor config keys with `airflow config update`.
8. Providers: upgrade to versions that support 3.x (most require it since late 2025); Cosmos ≥ 1.10.

---

## 10. Common failure modes

| Symptom | Likely cause → fix |
|---|---|
| DAG missing from UI | import error (`airflow dags list-import-errors`); wrong folder/bundle; `start_date` missing |
| "Task stuck in queued" | no worker slots (pools/parallelism), executor misconfig, triggerer not running for deferrables |
| Parse time warnings / scheduler slow | top-level API/DB calls, heavy imports at module level, thousands of static tasks → map dynamically |
| `logical_date is None` errors | manual trigger in 3.x; use `data_interval_*`/`run_id` or `Param`s |
| `AttributeError` on `execution_date`, `ImportError: airflow.operators.python` | 2.x code on 3.x — §9 |
| XCom too large / serialization error | dataframe in XCom → write Parquet, pass the path; object-storage XCom backend |
| Duplicate rows after retry | non-idempotent load → merge/replace-partition (`pipeline-patterns.md` §2) |
| Sensor eats all worker slots | `mode="poke"` → `reschedule` or `deferrable=True` |
| dbt/lib version conflicts on install | share a venv with Airflow → `@task.external_python` with a dedicated venv |
| Backfill runs in parallel and hammers source | set `max_active_runs`, pool, run `airflow backfill create` with `--max-active-runs 1` |
