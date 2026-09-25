# Fivetran

Fully managed SaaS ELT: hundreds of prebuilt connectors that land source data into a warehouse/lake schema with no code, then dbt does the transformation. Load this when the user names Fivetran or wants "just get Salesforce/Postgres/Shopify into Snowflake/BigQuery/Databricks/Redshift/Fabric with zero ops".

## Contents
1. Mental model
2. What lands in the warehouse (system columns, naming, deletes, schema changes)
3. Sync behaviour and CDC
4. REST API from Python
5. Custom sources: Connector SDK (Python)
6. Orchestrate from Airflow
7. dbt on top of Fivetran
8. Infrastructure-as-code
9. Cost and pitfalls

---

## 1. Mental model

- **Connection** (formerly "connector"): one source → one destination, owns a destination **schema** (one per connection; `schema_prefix` for databases → one schema per source database schema).
- Fivetran pulls (API/CDC) on a **sync frequency** (1 min–24 h depending on plan); the first sync is a **historical** load, later syncs are **incremental**. You don't write extraction code, choose cursors, or manage state.
- It **never transforms**; your staging models handle types, names and soft deletes. Anything "smart" (hashing, column blocking) is configured per table/column in the UI/API.
- Where it fits: reliable, boring ingestion of well-known sources; cost scales with data change volume, not engineer time.

---

## 2. What lands in the warehouse

- Naming: source objects become lowercase snake_case tables/columns (`OrderLines` → `order_lines`); reserved words and invalid chars are sanitized; **column names may differ from the source** — read the connector's schema page.
- System columns on every table:
  - `_fivetran_synced` — timestamp of the last sync that touched the row → use as `loaded_at_field` for dbt freshness.
  - `_fivetran_deleted` — `true` when the row was deleted at source (soft delete; Fivetran does not physically delete unless configured). Filter or carry through in staging: `where not coalesce(_fivetran_deleted, false)`.
  - `_fivetran_id` — surrogate hash PK when the source table has no primary key (then rows are append/dedupe candidates).
  - `_fivetran_index` for ordered nested arrays; `_fivetran_start/_fivetran_end/_fivetran_active` when **History Mode** (SCD2 at ingestion) is enabled.
- Nested JSON from APIs is unpacked into child tables with FK columns back to the parent (e.g. `order` → `order_line_item`).
- Schema drift: new columns/tables appear automatically (configurable: allow all / allow columns / block); type widening handled; column deletions are kept with nulls. Your staging model still lists columns explicitly.

---

## 3. Sync behaviour and CDC

- Databases: log-based CDC where possible — PostgreSQL logical replication (`wal_level=logical`, publication, a Fivetran-owned slot), MySQL binlog, SQL Server Change Tracking / CDC, Oracle LogMiner; fallbacks (XMIN for Postgres, Teleport/"snapshot diff" sync) when logs aren't available — slower and heavier on the source.
- SaaS APIs: connector-specific cursors with automatic rate-limit handling; some objects are full-refresh each sync (check "sync notes" per connector) — those inflate active rows.
- **Re-sync** (table or whole connection) rewrites history from scratch: expensive in MAR and source load; do it deliberately, off-peak.
- Priority-first sync delivers recent data before backfilling history on the initial load (useful for large tables).
- Failures/breakage surface as connection status (`broken`, `paused`, `incomplete`); subscribe to **webhooks** (`sync_end`, `connection_broken`) or poll the API from Airflow rather than watching the UI.

---

## 4. REST API from Python

Basic auth with API key/secret (create in Account settings; scope to a **system key** for automation). Base `https://api.fivetran.com/v1`. Fivetran renamed connectors → connections in 2025; use `/v1/connections/...` (older docs and SDKs use `/v1/connectors/...` — verify which your account/API version accepts).

```python
import base64, time, httpx

class Fivetran:
    def __init__(self, key: str, secret: str):
        token = base64.b64encode(f"{key}:{secret}".encode()).decode()
        self.c = httpx.Client(base_url="https://api.fivetran.com/v1",
                              headers={"Authorization": f"Basic {token}", "Accept": "application/json;version=2"},
                              timeout=30)

    def trigger_sync(self, connection_id: str, force: bool = False) -> None:
        self.c.post(f"/connections/{connection_id}/sync", json={"force": force}).raise_for_status()

    def status(self, connection_id: str) -> dict:
        r = self.c.get(f"/connections/{connection_id}"); r.raise_for_status()
        return r.json()["data"]

    def wait(self, connection_id: str, poll_s: int = 30, timeout_s: int = 3600) -> dict:
        started = self.status(connection_id)["succeeded_at"]
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            d = self.status(connection_id)
            if d["status"]["sync_state"] != "syncing" and d["succeeded_at"] != started:
                return d
            if d["failed_at"] and d["failed_at"] > (d["succeeded_at"] or ""):
                raise RuntimeError(f"Fivetran sync failed for {connection_id}")
            time.sleep(poll_s)
        raise TimeoutError(connection_id)
```
Other useful endpoints: list connections (`GET /connections?group_id=`), pause/resume (`PATCH /connections/{id}` with `{"paused": true}`), modify schema config (`PATCH /connections/{id}/schemas/{schema}/tables/{table}` `{"enabled": false}`), create connection (`POST /connections` with `service`, `group_id`, `config`), re-sync (`POST /connections/{id}/resync`). Rate limits apply per account — cache statuses; don't poll every 2 s.

---

## 5. Custom sources: Connector SDK (Python)

For an API Fivetran doesn't cover, write a Python connector that Fivetran hosts and schedules (no infra of your own):

```bash
uv add fivetran-connector-sdk
```
```python
# connector.py
from fivetran_connector_sdk import Connector, Operations as op, Logging as log
import httpx

def schema(configuration: dict) -> list[dict]:
    return [{"table": "tickets", "primary_key": ["id"],
             "columns": {"id": "STRING", "updated_at": "UTC_DATETIME", "status": "STRING"}}]

def update(configuration: dict, state: dict):
    since = state.get("tickets_cursor", "1970-01-01T00:00:00Z")
    with httpx.Client(base_url=configuration["base_url"],
                      headers={"Authorization": f"Bearer {configuration['api_key']}"}, timeout=30) as c:
        cursor = None
        while True:
            page = c.get("/tickets", params={"updated_since": since, "cursor": cursor}).raise_for_status().json()
            for t in page["data"]:
                yield op.upsert(table="tickets", data={"id": t["id"], "updated_at": t["updated_at"], "status": t["status"]})
                since = max(since, t["updated_at"])
            yield op.checkpoint(state={"tickets_cursor": since})    # persist progress; safe to resume here
            cursor = page.get("next_cursor")
            if not cursor:
                break

connector = Connector(update=update, schema=schema)
```
- `op.upsert`/`op.update`/`op.delete`/`op.checkpoint`; unspecified columns are inferred. Checkpoint often (every page) so retries don't restart.
- Local run writes to a DuckDB `warehouse.db` for inspection: `fivetran debug --configuration configuration.json`. Deploy: `fivetran deploy --api-key <base64 key:secret> --destination <dest_name> --connection <name> --configuration configuration.json`.
- Secrets go in `configuration.json` (deployed encrypted), never in code; `requirements.txt` next to `connector.py` for extra libs.
- Use the SDK when the source must be scheduled/monitored like every other Fivetran connection; use plain Python + Airflow when you need control over the destination layout or the volume is trivial.

---

## 6. Orchestrate from Airflow

Provider: `airflow-provider-fivetran-async` (Astronomer-maintained; check the version supports your Airflow 3.x). Airflow connection type **Fivetran**: `login` = API key, `password` = API secret (`AIRFLOW_CONN_FIVETRAN_DEFAULT='fivetran://<key>:<secret>@'`).

```python
from airflow.sdk import dag, Asset
from fivetran_provider_async.operators import FivetranOperator
from datetime import datetime

raw_shop = Asset(name="raw_shop", uri="snowflake://raw/fivetran_shop")

@dag(dag_id="ingest_shop", schedule="0 */2 * * *", start_date=datetime(2025,1,1), catchup=False, max_active_runs=1)
def ingest_shop():
    FivetranOperator(
        task_id="sync_shop",
        connector_id="bright_meander",     # the connection id from the Fivetran UI/API
        deferrable=True,                   # waits in the triggerer, not on a worker
        wait_for_completion=True,
        outlets=[raw_shop],                # dbt DAG scheduled on this asset
    )
ingest_shop()
```
- `FivetranSensor` waits for a sync that Fivetran's own schedule started (`completed_after_time` semantics) — use when you'd rather let Fivetran schedule and Airflow just gate dbt.
- Keep Fivetran's own schedule **paused** or set to manual when Airflow triggers it, otherwise you get double syncs and MAR you didn't budget.
- If the provider lags Airflow releases, the `httpx` client in §4 inside a `@task` plus `@task.sensor`/deferrable custom trigger is a 40-line substitute.

---

## 7. dbt on top of Fivetran

- Fivetran maintains dbt packages per connector: `fivetran/<source>_source` (staging models with Fivetran's column names and `_fivetran_deleted` handling) and `fivetran/<source>` (marts). Add via `packages.yml`, set `vars: {<source>_schema: fivetran_shop, <source>_database: raw}`. Good starting point; still review grain and cost before adopting the marts.
- `fivetran/fivetran_utils` has helpers for Fivetran-specific patterns (`fill_staging_columns`, JSON parsing across warehouses).
- Fivetran can run your dbt project itself after syncs ("Transformations"/Quickstart). Prefer **Airflow-triggered dbt** when Airflow already exists — one control plane, one alerting path; use Fivetran-scheduled transformations only for teams without an orchestrator.
- Staging rules for Fivetran tables: `loaded_at_field: _fivetran_synced`, filter `_fivetran_deleted`, dedupe only if `_fivetran_id` tables (no PK) can carry duplicates.

---

## 8. Infrastructure-as-code

Terraform provider `fivetran/fivetran`: `fivetran_group` (destination group), `fivetran_destination`, `fivetran_connector`/`fivetran_connection` + `fivetran_connector_schedule` + `fivetran_connector_schema_config` (which tables/columns sync). Treat connection config as code; the UI is for inspection. Same for webhooks and team access.

---

## 9. Cost and pitfalls

- **Pricing is consumption-based on Monthly Active Rows (MAR)** — rows inserted/updated/deleted per month per connection (per-connection pricing since 2025; verify the current model). High-churn tables (sessions, events, audit logs) can cost more than all others combined: block them, or ingest via another path.
- Full-refresh objects in API connectors count every row every sync → lower sync frequency for those or block them.
- Re-syncs and History Mode multiply MAR.
- Column blocking/hashing for PII at source; otherwise raw contains it and you must lock the schema down.
- Source impact: CDC needs `wal_level=logical`/binlog retention; an unconsumed slot (paused connection) fills the source disk — pause with care, drop when retiring.
- Naming surprises: check the connector's ERD; write staging models from the actual landed schema (`dbt run-operation generate_source`), not from the source system's docs.
- Freshness expectations: Fivetran sync frequency ≠ warehouse availability; historical syncs can take days for big tables; set dbt freshness thresholds to match the plan's frequency.
- Type mapping: money as `numeric`, but some connectors land JSON as `variant`/string — cast in staging.
- No transformations, no filtering rows at source (except some connectors' "sync mode" options) — if you need row-level filtering before landing, Fivetran is the wrong tool for that table.
