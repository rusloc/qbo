# Airbyte

Open-source (self-hosted) or Cloud ELT with the largest connector catalogue and three ways to build your own connector — plus **PyAirbyte**, which runs any Airbyte source inside a Python process without the platform. Load this when the user names Airbyte/PyAirbyte, wants self-hosted ingestion, or needs a connector that doesn't exist yet.

## Contents
1. Editions and mental model
2. Sync modes, namespaces and what lands in the destination
3. Building connectors: Connector Builder → low-code CDK → Python CDK
4. PyAirbyte: connectors inside your Python pipeline
5. Airbyte API from Python
6. Orchestrate from Airflow
7. dbt on top of Airbyte
8. Infrastructure-as-code
9. Cost and pitfalls

---

## 1. Editions and mental model

| Edition | Run it with | Notes |
|---|---|---|
| Airbyte OSS (Core) | `abctl local install` (single-node, kind-based Kubernetes) or Helm chart on your own Kubernetes | Docker-compose is deprecated; needs real CPU/RAM (≥4 vCPU/8 GB for small use) |
| Airbyte Cloud | Managed, credit-based pricing | Fastest start; same connectors and API |
| Self-Managed Enterprise | Helm, SSO/RBAC/multi-workspace | Regulated environments |

Objects: **Source** (connector + config) → **Connection** (streams, sync modes, schedule, namespace) → **Destination**. A **sync** is a job; jobs have attempts with logs. State (cursors) is stored per connection stream.

Where it fits: cost-controlled or self-hosted ingestion, long-tail/custom APIs, teams that want to own the platform. The trade is operating it (OSS) and a more variable connector quality than Fivetran's certified set — check the connector's support level (Certified / Community / Marketplace) before betting a pipeline on it.

---

## 2. Sync modes, namespaces and destination tables

Sync modes per stream:
- **Full Refresh | Overwrite** — replaces the table each sync (small dims, no cursor).
- **Full Refresh | Append** — keeps history of full snapshots (rarely what you want).
- **Incremental | Append** — cursor-based, appends changed rows; dedupe downstream in dbt.
- **Incremental | Append + Deduped** — needs a **primary key** and a **cursor**; destination keeps latest row per PK (SCD-free upsert). Default choice for mutable entities.
- Database sources: CDC (Postgres logical replication `pgoutput`, MySQL binlog, SQL Server CDC, MongoDB change streams) or cursor-based; CDC gives deletes (`_ab_cdc_deleted_at`, `_ab_cdc_lsn`/`_ab_cdc_updated_at` columns).

What lands (Destinations V2, "typing and deduping"):
- Raw tables in `airbyte_internal.<namespace>_raw__stream_<stream>` with `_airbyte_raw_id`, `_airbyte_extracted_at`, `_airbyte_loaded_at`, `_airbyte_data` (JSON), `_airbyte_meta`, `_airbyte_generation_id`.
- Typed final tables in the destination namespace with your columns plus `_airbyte_raw_id`, `_airbyte_extracted_at`, `_airbyte_meta` (per-row type errors), `_airbyte_generation_id` (which refresh produced it).
- Option "disable final tables" keeps raw JSON only → cheaper writes, and dbt does the typing (good when dbt already owns staging).
- Namespace strategy: *Destination default* (all streams in one schema), *Mirror source* (schema per source schema), *Custom* (`${SOURCE_NAMESPACE}_raw`); plus a stream-name prefix. Choose once — changing it later means a refresh.
- **Refresh** (reloads a stream while keeping old data queryable via generation ids) vs **Clear** (deletes destination data and state). Schema changes: connection setting to propagate columns/streams automatically, ignore, or pause the connection on breaking changes.

dbt staging rules: `loaded_at_field: _airbyte_extracted_at`; for `Incremental | Append` dedupe on PK ordering by `_airbyte_extracted_at desc`; keep `_airbyte_meta` errors visible in a rejects model.

---

## 3. Building connectors

Escalate only as far as needed:
1. **Connector Builder (UI)** — declarative REST connector with auth, pagination, incremental cursor, partitioning, transformations; test inline against the live API; publish to your workspace. Produces a YAML manifest (the low-code CDK). Handles ~90 % of REST APIs.
2. **Low-code CDK (YAML manifest)** — the same manifest edited in git, run by `source-declarative-manifest`. Key blocks: `streams[].retriever` (`SimpleRetriever` with `requester`, `record_selector`, `paginator`), `incremental_sync: DatetimeBasedCursor` (`cursor_field`, `start_datetime`, `step`, `lookback_window`), `partition_router` for parent/child streams, `transformations` (`AddFields`, `RemoveFields`), `schema_loader`. Version-control it and load it into the platform via API/Terraform.
3. **Python CDK** (`uv add airbyte-cdk`) — for non-HTTP sources or complex logic:
   ```python
   from airbyte_cdk.sources import AbstractSource
   from airbyte_cdk.sources.streams.http import HttpStream

   class Tickets(HttpStream):
       url_base = "https://api.example.com/"
       primary_key = "id"
       cursor_field = "updated_at"
       def path(self, **kw): return "tickets"
       def next_page_token(self, response):
           return {"cursor": response.json().get("next_cursor")} if response.json().get("next_cursor") else None
       def request_params(self, stream_state, next_page_token=None, **kw):
           return {"updated_since": (stream_state or {}).get("updated_at", "1970-01-01"), **(next_page_token or {})}
       def parse_response(self, response, **kw): yield from response.json()["data"]
       def get_updated_state(self, current, latest):
           return {"updated_at": max((current or {}).get("updated_at", ""), latest["updated_at"])}

   class SourceExample(AbstractSource):
       def check_connection(self, logger, config): return True, None
       def streams(self, config): return [Tickets(authenticator=TokenAuthenticator(config["api_key"]))]
   ```
   Scaffold with the generator in the Airbyte repo (`airbyte-integrations/connector-templates/generator`), test with `pytest` + Connector Acceptance Tests, package as a Docker image, register in the platform as a custom connector.

Prefer 1 → 2 → 3; a Python CDK connector is a service you now maintain.

---

## 4. PyAirbyte

`uv add airbyte` (package name `airbyte`; Python ≥3.10). Runs connectors as subprocesses in per-connector virtualenvs (auto-installed) or Docker, caches results in DuckDB (default) / Postgres / Snowflake / BigQuery, keeps incremental state in the cache. Ideal for: a data pipeline that needs a source connector but not the Airbyte platform, notebooks, Airflow tasks, prototypes.

```python
import airbyte as ab

source = ab.get_source(
    "source-github",
    config={"repositories": ["acme/app"], "credentials": {"personal_access_token": ab.get_secret("GITHUB_TOKEN")}},
    install_if_missing=True,          # or docker_image=True for non-Python connectors
)
source.check()
source.select_streams(["issues", "pull_requests"])   # select_all_streams() for everything

cache = ab.get_default_cache()        # DuckDB file under .cache/; ab.new_local_cache("gh") for a named one
result = source.read(cache=cache)     # incremental on subsequent runs: state lives in the cache

issues = result["issues"].to_pandas()                # to_arrow(), to_sql_table(), to_documents()
result.streams["issues"].to_arrow().to_pandas()

# hand off to a real destination without the platform
dest = ab.get_destination("destination-snowflake", config={...})
dest.write(result)                                   # or dest.write(source) to stream straight through
```
- `ab.get_secret()` pulls from env/.env/Colab/prompt; never inline tokens.
- `source.get_records("issues")` for quick exploration without a cache; `source.get_available_streams()`, `source.discovered_catalog`.
- Inside Airflow: run in `@task.external_python` with a prebuilt venv containing `airbyte`; point the cache at a persistent path or a Postgres cache so state survives pod restarts; write Parquet/warehouse from the result and let dbt take over.
- Connector installs happen at first run (pip in a venv) — bake them into the image for prod.

---

## 5. Airbyte API from Python

Public API base: Cloud `https://api.airbyte.com/v1`; OSS/abctl `http://<host>:8000/api/public/v1`. Auth: create an **Application** (Settings → Applications) → `client_id`/`client_secret` → `POST /v1/applications/token` → bearer token (Cloud and recent OSS). The official SDK is `airbyte-api` (`uv add airbyte-api`); plain `httpx` shown for clarity:

```python
import time, httpx

class Airbyte:
    def __init__(self, base: str, client_id: str, client_secret: str):
        self.c = httpx.Client(base_url=base, timeout=30)
        tok = self.c.post("/applications/token", json={"client_id": client_id, "client_secret": client_secret,
                                                       "grant-type": "client_credentials"}).raise_for_status().json()
        self.c.headers["Authorization"] = f"Bearer {tok['access_token']}"

    def trigger_sync(self, connection_id: str) -> str:
        return self.c.post("/jobs", json={"connectionId": connection_id, "jobType": "sync"}).raise_for_status().json()["jobId"]

    def wait(self, job_id: str, poll_s: int = 30, timeout_s: int = 7200) -> dict:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            job = self.c.get(f"/jobs/{job_id}").raise_for_status().json()
            if job["status"] in ("succeeded",): return job
            if job["status"] in ("failed", "cancelled", "incomplete"): raise RuntimeError(f"Airbyte job {job_id}: {job['status']}")
            time.sleep(poll_s)
        raise TimeoutError(job_id)
```
Also: `GET /connections?workspaceIds=`, `POST /connections` (streams config, schedule `{"scheduleType": "manual"}` when Airflow drives it), `PATCH /connections/{id}`, `GET /jobs?connectionId=&status=`, `POST /jobs` with `"jobType": "reset"`/`"refresh"`. Token lifetime is short — refresh on 401.

---

## 6. Orchestrate from Airflow

Provider: `apache-airflow-providers-airbyte` (≥4.x talks to the public API above; older 3.x used the internal `/api/v1` with basic auth). Airflow connection type **Airbyte**: host = public API base URL (`https://api.airbyte.com` or `http://airbyte-airbyte-server-svc:8001` for OSS in-cluster), login/password = client id/secret (or `extra` with `token` for OSS variants) — check the provider's docs for the exact fields of the installed version.

```python
from airflow.sdk import dag, Asset
from airflow.providers.airbyte.operators.airbyte import AirbyteTriggerSyncOperator
from airflow.providers.airbyte.sensors.airbyte import AirbyteJobSensor
from datetime import datetime

raw_gh = Asset(name="raw_github", uri="postgres://raw/github")

@dag(dag_id="ingest_github", schedule="0 */4 * * *", start_date=datetime(2025,1,1), catchup=False, max_active_runs=1)
def ingest_github():
    trigger = AirbyteTriggerSyncOperator(
        task_id="trigger_sync",
        airbyte_conn_id="airbyte_default",
        connection_id="8d3d4e5f-...",       # Airbyte connection UUID
        asynchronous=True,                  # returns job id immediately; sensor waits (frees the worker)
    )
    wait = AirbyteJobSensor(task_id="wait_sync", airbyte_conn_id="airbyte_default",
                            airbyte_job_id=trigger.output, poke_interval=60, mode="reschedule",
                            outlets=[raw_gh])
    trigger >> wait
ingest_github()
```
- Synchronous form (`asynchronous=False`, `wait_seconds`, `timeout`) blocks a worker slot; use only for short syncs. Newer provider versions support `deferrable=True` on the operator — prefer it when available.
- Set the Airbyte connection schedule to **manual** when Airflow triggers it.
- If the provider version and your Airflow/API don't line up, the `httpx` client in §5 inside `@task` + a deferrable custom trigger is the fallback.

---

## 7. dbt on top of Airbyte

- Airbyte no longer runs custom dbt transformations inside the platform ("normalization" became Destinations V2 typing/deduping); transformations belong to your dbt project scheduled by Airflow after the sync.
- Staging: explicit columns from the final tables (or `json_extract` from `_airbyte_data` if final tables are disabled), `loaded_at_field: _airbyte_extracted_at`, dedupe on PK for append modes, surface `_airbyte_meta.errors`.
- `dbt run-operation generate_source --args '{schema_name: github}'` to bootstrap sources; regenerate after schema propagation events.

---

## 8. Infrastructure-as-code

Terraform provider `airbytehq/airbyte` (`airbyte_source_*`, `airbyte_destination_*`, `airbyte_connection` with `configurations.streams[]` sync modes, `schedule`). Custom low-code connectors: keep `manifest.yaml` in git and publish via the Connector Builder API / `airbyte_source_custom`. OSS platform itself: Helm values in git; secrets via Kubernetes secrets / external-secrets.

---

## 9. Cost and pitfalls

- Cloud pricing is **credit-based** (rows for APIs, volume for databases/files); Full-Refresh streams and wide JSON payloads burn credits — pick incremental modes and select only needed streams.
- OSS is not free: Kubernetes, storage for logs/state, connector pods' CPU/RAM (a big Postgres CDC sync needs several GB), upgrades. `abctl` is single-node; production means a real cluster.
- Typing & deduping doubles storage (raw + final) and runs SQL on the warehouse after each sync — budget warehouse compute, or disable final tables and type in dbt.
- Cursor fields must be monotonically updated and non-null; rows updated without touching the cursor are missed (same caveat as any watermark; see `pipeline-patterns.md` §3). Deletes need CDC.
- Community connectors can change schemas or break on API changes; pin connector versions in the connection and read release notes before upgrading.
- Changing namespace/prefix/PK/cursor forces a refresh or clear — plan for the reload window.
- PyAirbyte: first run installs each connector's venv (slow, needs network); DuckDB default cache is local-disk state — for scheduled jobs use a Postgres cache or persist the cache path; not all connectors are Python (`docker_image=True` needs Docker).
- Secrets: Airbyte stores source configs encrypted, but exported connection JSON contains them — never commit exports.
