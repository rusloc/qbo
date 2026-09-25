# Python stack for data engineering

Read this before writing any Python for a pipeline. It fixes the tooling, the library choices, the project layout and the conventions so that every pipeline in a codebase looks the same.

## Contents
1. Tooling and environment
2. Library selection (dataframes, I/O, connectivity)
3. Project layout
4. Configuration and secrets
5. Connectivity recipes
6. Logging and observability
7. Testing
8. Performance rules of thumb
9. Style conventions

---

## 1. Tooling and environment

| Concern | Use | Why |
|---|---|---|
| Python version | 3.12 (3.13 fine when every dependency supports it) | Airflow 3, Polars, pydantic v2, dbt all support 3.12; avoid 3.14 until providers publish wheels |
| Env + deps + lockfile | `uv` (`uv init`, `uv add polars`, `uv sync`, `uv run pytest`) | One tool, reproducible `uv.lock`, fast; replaces pip/venv/pip-tools/poetry |
| Lint + format | `ruff` (`ruff check --fix . && ruff format .`) | Single tool; enable `AIR` rules for Airflow projects (`AIR3*` flags Airflow-3-incompatible code) |
| Types | `mypy --strict` or `pyright` on `src/` | Catches the classic None/str/datetime bugs at boundaries |
| Tests | `pytest` (+ `pytest-cov`, `hypothesis` for parsers) | |
| Pre-commit | `pre-commit` running ruff, mypy, `uv lock --check` | Stops unformatted code and drifted lockfiles reaching CI |
| Task runner | `just` or `make` | Documents the commands: `just test`, `just run-local` |

Minimal `pyproject.toml`:

```toml
[project]
name = "acme-pipelines"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "polars>=1.0",
  "pyarrow>=17",
  "duckdb>=1.1",
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "sqlalchemy>=2.0",
  "psycopg[binary]>=3.2",
  "httpx>=0.27",
  "tenacity>=8.3",
  "structlog>=24",
  "typer>=0.12",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-cov", "ruff", "mypy", "pre-commit", "hypothesis"]
airflow = ["apache-airflow>=3.1,<4"]   # install with the constraints file, see airflow.md
dbt = ["dbt-core>=1.10,<2", "dbt-postgres"]   # or dbt-snowflake / dbt-bigquery / dbt-duckdb

[tool.ruff]
line-length = 100
target-version = "py312"
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "AIR"]

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Keep Airflow and dbt in **separate environments** from the pipeline package when possible (they pin many transitive deps). In a monorepo: `uv` workspaces or one venv per top-level folder.

---

## 2. Library selection

### Dataframes and compute
- **Polars** — default for new code. Lazy API (`pl.scan_parquet(...).filter(...).collect()`), strict dtypes, multithreaded, streaming for larger-than-RAM. Use `pl.LazyFrame` end-to-end and `collect()` once.
- **pandas 2.x** — when a downstream library needs it (scikit-learn, some connectors, legacy code). Use `dtype_backend="pyarrow"` on reads and `pd.ArrowDtype` columns to avoid object dtypes. Convert with `pl.from_pandas` / `df.to_pandas()`.
- **PyArrow** — the interchange format. `pa.Table` for zero-copy hand-offs, `pyarrow.parquet` for writing with explicit schemas, `pyarrow.dataset` for partitioned reads, `pyarrow.flight`/ADBC for fast DB reads.
- **DuckDB** — in-process SQL over Parquet/CSV/Arrow/Polars. Use for local transforms, tests, ad-hoc profiling, and as the local dbt target (`dbt-duckdb`). `duckdb.sql("select ... from df")` works directly on a Polars/pandas frame.
- **Ibis** — optional when the same transform must run on DuckDB locally and Snowflake/BigQuery in prod without rewriting.
- **Spark (PySpark)** — only when data does not fit a single large machine or the platform is Databricks/Fabric Spark. Don't reach for it below ~100s of GB per run.

### I/O and formats
- Parquet everywhere between stages (`compression="zstd"`, row groups ~128 MB). CSV/JSON only at the edges (vendor drops, API responses). See `pipeline-patterns.md` §4 for partition layouts.
- Object storage: `fsspec` + `s3fs` / `adlfs` / `gcsfs`, or `pyarrow.fs`. Airflow tasks: `ObjectStoragePath` from `airflow.sdk`.
- HTTP APIs: `httpx` (sync or async, timeouts mandatory), `tenacity` for retries, `pydantic` models for responses.
- Excel: `polars.read_excel` (fastexcel) or `openpyxl` for writing.

### Connectivity
- SQLAlchemy 2.x `create_engine` + `text()` for control-plane queries (watermarks, metadata); bulk data goes through the warehouse's native bulk path, never row-by-row inserts.
- Drivers: PostgreSQL `psycopg` (v3, `COPY` support), SQL Server / Fabric `mssql-python` or `pyodbc` (ODBC 18), Snowflake `snowflake-connector-python` (`write_pandas`, `COPY INTO`), BigQuery `google-cloud-bigquery` (`load_table_from_dataframe`), Databricks `databricks-sql-connector`, DuckDB native.
- Fast reads: `connectorx` (`cx.read_sql(conn, query, return_type="polars", partition_on=...)`) or ADBC drivers; both avoid the Python row loop.

### Validation
- `pydantic` v2 for records crossing a boundary (API → your code).
- `pandera` (supports Polars and pandas) for dataframe schemas inside the pipeline.
- dbt tests for anything already in the warehouse (see `dbt.md`). Don't duplicate warehouse checks in Python.

---

## 3. Project layout

```
acme-pipelines/
├── pyproject.toml
├── uv.lock
├── README.md
├── src/acme_pipelines/
│   ├── __init__.py
│   ├── config.py            # pydantic-settings Settings
│   ├── logging.py           # structlog setup
│   ├── sources/             # one module per source system: extract functions only
│   │   ├── stripe.py
│   │   └── postgres_orders.py
│   ├── sinks/               # load functions: warehouse, object storage
│   │   ├── parquet.py
│   │   └── snowflake.py
│   ├── transforms/          # pure functions on LazyFrame/Table; no I/O
│   ├── pipelines/           # compose source → transform → sink for one interval
│   │   └── orders.py        # run(interval_start, interval_end, settings)
│   └── cli.py               # typer app: `acme-pipelines run orders --start ... --end ...`
├── dags/                    # Airflow DAGs; thin — they call src.pipelines.* (see airflow.md)
├── dbt/                     # dbt project (see dbt.md)
└── tests/
    ├── conftest.py          # fixtures: tmp parquet, duckdb conn, sample frames
    ├── test_transforms.py
    └── test_pipelines.py
```

Rules that make this layout work:
- **Extract, transform, load are separate functions with typed signatures.** `extract(...) -> pl.LazyFrame | pa.Table | Iterator[pa.RecordBatch]`, `transform(lf: pl.LazyFrame) -> pl.LazyFrame` (pure), `load(table, target)`.
- **A pipeline is a function of an interval**: `run(start: datetime, end: datetime, settings: Settings) -> RunResult`. Airflow, the CLI, and tests all call the same function. This is what makes backfills trivial.
- **DAG files contain no business logic.** They import from the package. If a DAG grows a helper function, it belongs in `src/`.
- `RunResult` (a dataclass/pydantic model) carries `rows_extracted`, `rows_loaded`, `max_watermark`, `output_paths` so the caller can log/assert on them.

---

## 4. Configuration and secrets

```python
# src/acme_pipelines/config.py
from pydantic import SecretStr, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ACME_", env_file=".env", extra="ignore")

    env: str = "dev"
    warehouse_dsn: PostgresDsn
    stripe_api_key: SecretStr
    landing_bucket: str = "s3://acme-landing-dev"
    lookback_minutes: int = 30

settings = Settings()  # instantiate once at the composition root, pass it down
```

- Environment variables in prod (`ACME_STRIPE_API_KEY=...`), `.env` locally (git-ignored, `.env.example` committed).
- In Airflow use Connections/Variables backed by a secrets backend (see `airflow.md` §5) and pass values into `Settings` explicitly; don't read Airflow objects deep inside library code.
- Never log a `SecretStr` (its `repr` is masked, `.get_secret_value()` only at the call site).
- Per-environment differences (bucket names, schemas) are config, not `if env == "prod"` branches.

---

## 5. Connectivity recipes

**Batch-read from a database into Parquet without loading everything into RAM:**
```python
import pyarrow as pa, pyarrow.parquet as pq
import psycopg

def dump_query(dsn: str, sql: str, params: dict, out_path: str, batch_rows: int = 200_000) -> int:
    rows = 0
    with psycopg.connect(dsn) as conn, conn.cursor(name="stream") as cur:  # server-side cursor
        cur.itersize = batch_rows
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        writer = None
        for batch in iter(lambda: cur.fetchmany(batch_rows), []):
            tbl = pa.Table.from_pylist([dict(zip(cols, r)) for r in batch])
            writer = writer or pq.ParquetWriter(out_path, tbl.schema, compression="zstd")
            writer.write_table(tbl)
            rows += tbl.num_rows
        if writer:
            writer.close()
    return rows
```
For large tables prefer `connectorx.read_sql(..., partition_on="id", partition_num=8, return_type="arrow")`.

**Bulk-load into PostgreSQL (fastest path is COPY):**
```python
def copy_arrow_to_postgres(dsn: str, table: pa.Table, target: str) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        with cur.copy(f"COPY {target} ({', '.join(table.column_names)}) FROM STDIN (FORMAT BINARY)") as copy:
            for row in table.to_pylist():
                copy.write_row(tuple(row.values()))
        conn.commit()
```
Load into a staging table, then `MERGE`/`INSERT ... ON CONFLICT` into the target inside one transaction (pattern in `pipeline-patterns.md` §2).

**Snowflake / BigQuery / Databricks**: write Parquet to a stage/bucket, then `COPY INTO` / `LOAD DATA` / `COPY INTO` from the warehouse side. `write_pandas` and `load_table_from_dataframe` do this for you for medium sizes.

**HTTP API with retries, pagination and typing:**
```python
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type
from pydantic import BaseModel

class Charge(BaseModel):
    id: str
    amount: int
    created: int

@retry(stop=stop_after_attempt(5), wait=wait_exponential_jitter(1, 30),
       retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)))
def _get(client: httpx.Client, url: str, params: dict) -> dict:
    r = client.get(url, params=params, timeout=30)
    if r.status_code == 429:
        raise httpx.HTTPStatusError("rate limited", request=r.request, response=r)
    r.raise_for_status()
    return r.json()

def iter_charges(client: httpx.Client, since: int):
    cursor = None
    while True:
        page = _get(client, "/v1/charges", {"created[gte]": since, "starting_after": cursor, "limit": 100})
        for raw in page["data"]:
            yield Charge.model_validate(raw)
        if not page.get("has_more"):
            break
        cursor = page["data"][-1]["id"]
```

---

## 6. Logging and observability

- `structlog` with JSON output in prod, console renderer locally. Bind `run_id`, `pipeline`, `interval_start`, `interval_end` once at the start of `run()`; every later log line inherits them.
- Log **counts, durations, watermarks, output paths** at INFO; individual records never (PII + volume).
- Emit metrics where a collector exists (OpenTelemetry / StatsD / Prometheus pushgateway): rows in/out, bytes written, duration, last successful interval. These feed freshness alerts.
- Lineage: if the org uses OpenLineage/Marquez/DataHub, emit from Airflow's OpenLineage provider rather than hand-rolling.

---

## 7. Testing

- **Transforms are pure → unit test them with small frames.** `polars.testing.assert_frame_equal(result.collect(), expected)`; build `expected` by hand, not by running the function.
- **Sources**: test parsers/pagination against recorded fixtures (`respx` for httpx, saved JSON pages). No live network in unit tests.
- **Sinks**: test against DuckDB or a PostgreSQL in Docker (`testcontainers`) — real `MERGE` semantics matter.
- **Pipelines**: an integration test that runs `run()` twice for the same interval and asserts the row count is unchanged (idempotency test). This one test catches most production bugs.
- **DAGs**: import test + `dag.test()` (see `airflow.md` §7).
- **dbt**: `dbt build` against DuckDB in CI with seeds as fixtures (see `dbt.md` §8).
- Use `hypothesis` for anything that parses dates, currencies, or free-text IDs.

---

## 8. Performance rules of thumb

- Stay columnar: Arrow/Polars/Parquet end-to-end; the moment you see `for row in df.iterrows()` or `to_pylist()` on millions of rows, stop and rewrite.
- Push filters/aggregations to the source database or warehouse; Python moves data, it shouldn't grind it.
- Stream: server-side cursors, `iter_batches`, `pl.scan_*` + `sink_parquet` for larger-than-memory.
- Parallelism: partition by key range or date and run in Airflow's dynamic task mapping, not with threads inside one task (the scheduler already gives you retries and observability per partition).
- Measure before optimizing: `time`, `pl.Config.set_verbose`, `EXPLAIN` on the warehouse; Parquet row-group and file size (aim 100–500 MB per file) fix most "slow read" complaints.

---

## 9. Style conventions

- Type hints on every public function; `datetime` objects are timezone-aware UTC (`datetime.now(UTC)`, never naive).
- Function names say what moves where: `extract_stripe_charges`, `load_parquet_to_snowflake`, `merge_into_orders`.
- Constants for schema/table names live in one module; SQL strings use `text()` with bound parameters, never f-strings with user data.
- Any SQL you emit follows the house formatter rules (`sql-style-formatter` / `dax-sql-formatter` skills if present).
- Docstring on `run()` states the interval semantics (`[start, end)`), the watermark column, and what is overwritten.
