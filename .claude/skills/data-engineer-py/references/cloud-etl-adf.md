# Azure Data Factory (and Fabric Data Factory)

Azure's managed integration service: visual pipelines of activities, a Copy activity that moves data between ~100 stores at scale, Self-hosted Integration Runtime for on-prem/VNet sources, and triggers for schedule/tumbling-window/event runs. Load this when the user is on Azure/Fabric, mentions ADF, Copy activity, Self-hosted IR, Data Flows, Fabric Data Pipelines, Dataflow Gen2 or Copy Job.

## Contents
1. Building blocks and mental model
2. ADF vs Fabric Data Factory
3. Standard patterns (landing, incremental watermark, metadata-driven, tumbling window)
4. Expression language cheat-sheet
5. Python: SDK, REST, calling Python from ADF
6. Orchestrate from Airflow
7. CI/CD and infrastructure-as-code
8. Cost model
9. Pitfalls

---

## 1. Building blocks and mental model

| Object | Role |
|---|---|
| **Linked service** | Connection definition (store or compute) — secrets via Key Vault references, auth via managed identity where possible |
| **Dataset** | Named, parameterized pointer to data inside a linked service (table, folder, file format) |
| **Integration runtime (IR)** | Where activities execute: *Azure IR* (serverless; use managed VNet for private endpoints), *Self-hosted IR* (Windows service on your VM/on-prem, reaches private networks, can be clustered up to 4 nodes), *Azure-SSIS IR* (lift-and-shift SSIS) |
| **Pipeline** | DAG of activities with parameters/variables; `Execute Pipeline` for reuse; concurrency setting |
| **Activities** | *Copy* (the workhorse), *Lookup* (small result sets ≤5000 rows/4 MB), *Get Metadata*, *ForEach* (`batchCount` ≤50, `isSequential`), *If/Switch/Until/Filter/Wait/Fail*, *Set/Append Variable*, *Web/WebHook* (REST calls), *Script*/*Stored Procedure* (SQL), *Mapping Data Flow* (Spark, no-code transforms), *Notebook* (Databricks/Synapse/Fabric), *Azure Function*, *Custom* (Azure Batch, run any Python), *Delete*, *Validation* |
| **Triggers** | *Schedule* (cron-like), *Tumbling window* (fixed intervals with retry, dependencies, backfill/rerun — the idempotent choice), *Storage event* (blob created/deleted), *Custom event* (Event Grid), manual/REST |
| **Change Data Capture** | Top-level CDC resource: continuous or scheduled source→sink replication with no pipeline authoring (evaluate before building CDC pipelines by hand) |

Mental model: ADF is an **orchestrated mover**, not a transformation engine. Use Copy to land raw data (Parquet in ADLS Gen2 or raw tables in the warehouse), keep transformation in dbt/SQL/Spark, and keep business logic out of Data Flows unless the team is no-code by policy.

---

## 2. ADF vs Fabric Data Factory

Fabric Data Factory (inside Microsoft Fabric, OneLake-centric) reuses the ADF pipeline model with differences:
- **Data pipelines**: same activities and expression language; no linked services/datasets — activities use workspace **connections** directly; Fabric-native activities (Notebook, Dataflow Gen2, Copy Job, Semantic model refresh, Invoke pipeline). Existing ADF factories can be **mounted** into a Fabric workspace to run alongside.
- **Dataflow Gen2**: Power Query transformations with destinations (Lakehouse/Warehouse) — for analysts; not for volume.
- **Copy job**: standalone, incremental/CDC-aware copy without a pipeline — the quickest "keep this table in sync" option.
- **Mirroring**: near-real-time replication of Azure SQL/Snowflake/Cosmos/etc. into OneLake — zero-ETL for supported sources.
- **Apache Airflow job**: managed Airflow inside Fabric (Astronomer-based) if the org wants Airflow without running it.
- Triggering: Fabric Job Scheduler REST API (`POST https://api.fabric.microsoft.com/v1/workspaces/{ws}/items/{item}/jobs/instances?jobType=Pipeline`) with an Entra token; schedules configured on the item.

Rule: same patterns as below; when the destination is a Fabric Warehouse and dbt is involved, hand the dbt part to the `dbt-fabric-warehouse` skill.

---

## 3. Standard patterns

### Landing raw files
Copy: source (table/query/API/file) → sink ADLS Gen2 Parquet, folder `raw/<source>/<object>/dt=@{formatDateTime(pipeline().parameters.windowStart,'yyyy-MM-dd')}/` with `part-@{pipeline().RunId}.parquet`; re-run overwrites the same folder. Use `Binary` datasets for lift-and-shift of files, `modifiedDatetimeStart/End` or storage-event triggers for new-file pickup.

### Incremental load by watermark
1. **Lookup** old watermark from control table `etl.watermark` (`select watermark_value from etl.watermark where table_name = '@{item().TableName}'`).
2. **Lookup** new watermark from source (`select max(updated_at) as new_wm from ...`).
3. **Copy** with query `select * from dbo.Orders where updated_at > '@{activity('LookupOld').output.firstRow.watermark_value}' and updated_at <= '@{activity('LookupNew').output.firstRow.new_wm}'` → staging table (`preCopyScript: truncate table stg.orders`) or Parquet partition.
4. **Script/Stored Procedure** to `MERGE` staging into target and update the watermark — same transaction.
Copy activity can also `upsert` directly into Azure SQL/Synapse/Fabric Warehouse (`writeBehavior: upsert`, `upsertSettings.keys`) for simpler cases; use staged copy (`enableStaging`) with COPY/PolyBase for warehouses.

### Metadata-driven ingestion (dozens of tables)
Control table (`source_system, schema_name, table_name, watermark_column, target_path, is_active, load_type`) → **Lookup** (list of tables) → **ForEach** (`batchCount` 8–20, parallel) → **Execute Pipeline** `pl_load_table` (parameterized datasets: `@dataset().SchemaName`, `@dataset().TableName`) → log to `etl.run_log`. ADF's "Copy Data tool → metadata-driven" wizard scaffolds this. Nested ForEach is not allowed — split into child pipelines.

### Tumbling window trigger for interval-driven, idempotent runs
Trigger with `frequency: Hour/Day`, `interval`, `startTime`, `delay`, `maxConcurrency: 1`, `retryPolicy`; pipeline parameters `windowStart = @trigger().outputs.windowStartTime`, `windowEnd = @trigger().outputs.windowEndTime`. Rerunning a window reprocesses exactly that interval; dependencies (self-dependency or on another trigger) enforce ordering; backfill = create the trigger with a past `startTime`. This mirrors Airflow's `data_interval_*` (see `pipeline-patterns.md` §2, §5).

### Calling out
- **Web** activity → REST (e.g. trigger a Fivetran/Airbyte sync, notify Slack, call an Azure Function), managed identity or Key Vault secret in header.
- **Azure Function / Custom (Azure Batch) / Databricks or Fabric Notebook** activity → run Python for anything the built-ins can't do; pass parameters, return a small JSON to `@activity('X').output`.
- **Execute Pipeline** for modularity; **Fail** activity for explicit error semantics; **Web**/**WebHook** with callback for long-running externals.

---

## 4. Expression language cheat-sheet

Expressions start with `@`; inside string literals use interpolation `@{...}`; escape a literal `@` as `@@`; strings inside expressions use single quotes.

```
@pipeline().parameters.windowStart          @pipeline().RunId   @pipeline().TriggerTime   @pipeline().DataFactory
@variables('fileList')                      @item()   @item().TableName            (inside ForEach)
@activity('LookupOld').output.firstRow.watermark_value
@activity('LookupList').output.value        (array for ForEach)   @activity('Copy').output.rowsCopied / .rowsRead / .errors
@trigger().outputs.windowStartTime          @trigger().startTime   @triggerBody().folderPath / .fileName   (storage event)
@concat('raw/', item().TableName, '/dt=', formatDateTime(pipeline().parameters.windowStart, 'yyyy-MM-dd'))
@formatDateTime(utcnow(), 'yyyy-MM-ddTHH:mm:ssZ')   @addDays(utcnow(), -1)   @addHours(...)   @convertTimeZone(...)
@if(equals(item().load_type, 'full'), 'truncate table stg.x', '')     @coalesce(activity('L').output.firstRow.x, '1900-01-01')
@string(int(pipeline().parameters.n))   @json(...)   @array(...)   @length(...)   @empty(...)   @contains(...)   @split(...)
@dataset().TableName   @linkedService().ServerName   (parameterized datasets / linked services)
```
Debug: use the expression builder's preview, a `Set Variable` activity to print intermediate values, and the activity **output** JSON in the monitoring view. Lookup `firstRow` vs `value[]` is the most common mistake.

---

## 5. Python: SDK, REST, calling Python from ADF

```bash
uv add azure-identity azure-mgmt-datafactory
```
```python
from datetime import datetime, timedelta, UTC
import time
from azure.identity import DefaultAzureCredential
from azure.mgmt.datafactory import DataFactoryManagementClient
from azure.mgmt.datafactory.models import RunFilterParameters

client = DataFactoryManagementClient(DefaultAzureCredential(), subscription_id="...")
RG, DF = "rg-data-prod", "adf-acme-prod"

def run_pipeline(name: str, params: dict, poll_s: int = 30, timeout_s: int = 4 * 3600) -> dict:
    run = client.pipelines.create_run(RG, DF, name, parameters=params)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = client.pipeline_runs.get(RG, DF, run.run_id)
        if r.status in ("Succeeded",):
            return r.as_dict()
        if r.status in ("Failed", "Cancelled"):
            acts = client.activity_runs.query_by_pipeline_run(
                RG, DF, run.run_id,
                RunFilterParameters(last_updated_after=datetime.now(UTC) - timedelta(days=1),
                                    last_updated_before=datetime.now(UTC) + timedelta(hours=1)))
            failed = [(a.activity_name, a.error) for a in acts.value if a.status == "Failed"]
            raise RuntimeError(f"ADF run {run.run_id} {r.status}: {failed}")
        time.sleep(poll_s)
    raise TimeoutError(run.run_id)

run_pipeline("pl_load_orders", {"windowStart": "2025-03-01T00:00:00Z", "windowEnd": "2025-03-02T00:00:00Z"})
```
- Auth: `DefaultAzureCredential` → managed identity in Azure, `az login` locally, service principal via `AZURE_CLIENT_ID/AZURE_TENANT_ID/AZURE_CLIENT_SECRET` in CI. Role: **Data Factory Contributor** on the factory.
- REST directly: `POST https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.DataFactory/factories/{df}/pipelines/{name}/createRun?api-version=2018-06-01`; Fabric: the Job Scheduler endpoint in §2.
- Deploying definitions from Python: `client.pipelines.create_or_update(RG, DF, name, PipelineResource(activities=[...]))` — useful for generating many similar pipelines, but prefer git + ARM (§7) for auditability.
- Running Python **from** ADF: Azure Function activity (short jobs), Custom activity on Azure Batch (long jobs, any deps, reads `activity.json` for inputs), Databricks/Synapse/Fabric Notebook activity (Spark). Return values via activity output JSON.

---

## 6. Orchestrate from Airflow

Provider: `apache-airflow-providers-microsoft-azure`. Connection type **Azure Data Factory** (`azure_data_factory`): login = client id, password = client secret, extras `tenantId`, `subscriptionId`, optional defaults `resource_group_name`, `factory_name`; or managed identity with no credentials on Azure-hosted workers.

```python
from airflow.sdk import dag, Asset
from airflow.providers.microsoft.azure.operators.data_factory import AzureDataFactoryRunPipelineOperator
from datetime import datetime

raw_orders = Asset(name="raw_orders", uri="abfss://raw@acmelake.dfs.core.windows.net/orders")

@dag(dag_id="adf_load_orders", schedule="0 * * * *", start_date=datetime(2025,1,1), catchup=False, max_active_runs=1)
def adf_load_orders():
    AzureDataFactoryRunPipelineOperator(
        task_id="run_pl_load_orders",
        azure_data_factory_conn_id="adf_prod",
        pipeline_name="pl_load_orders",
        resource_group_name="rg-data-prod",
        factory_name="adf-acme-prod",
        parameters={"windowStart": "{{ data_interval_start.isoformat() }}",
                    "windowEnd": "{{ data_interval_end.isoformat() }}"},
        wait_for_termination=True,
        deferrable=True,                # waits in the triggerer
        check_interval=60,
        outlets=[raw_orders],
    )
adf_load_orders()
```
- `AzureDataFactoryPipelineRunStatusSensor(run_id=...)` when something else started the run; `AzureDataFactoryHook` for ad-hoc calls.
- Fabric items: newer provider versions ship `MSFabricRunItemOperator` (workspace id + item id, `job_type="Pipeline"`) — verify availability in the installed version; otherwise call the Job Scheduler API from a `@task`.
- Pass Airflow's interval into the pipeline parameters (as above) so ADF runs stay idempotent per interval; disable the ADF trigger when Airflow owns the schedule.

---

## 7. CI/CD and infrastructure-as-code

- Enable **git integration** (Azure DevOps or GitHub): collaboration branch `main`, feature branches per change, PR review of the JSON definitions; the UI is the editor, git is the source of truth.
- **Automated publish** (recommended over the manual Publish button): npm package `@microsoft/azure-data-factory-utilities` in the pipeline: `npm run build validate <repo> <factoryResourceId>` and `npm run build export <repo> <factoryResourceId> ArmTemplate` → deploy with `az deployment group create --template-file ArmTemplate/ARMTemplateForFactory.json --parameters ArmTemplate/ARMTemplateParametersForFactory.json <overrides>`; run the pre/post deployment script (stop triggers → deploy → start triggers).
- Parameterize per environment with `arm-template-parameters-definition.json` (linked service URLs, Key Vault names, IR names); global parameters included in ARM via factory settings.
- Factory, IRs, Key Vault, managed identities, RBAC via Bicep/Terraform (`azurerm_data_factory*`); pipelines/datasets can also be Terraform resources (`azurerm_data_factory_pipeline` with JSON) when the team prefers code-first over the UI.
- Secrets: Key Vault-backed linked services; managed identity to Key Vault, storage, SQL; no connection strings in JSON.

---

## 8. Cost model

- **Copy activity**: DIU-hours on Azure IR (2–256 DIUs, auto by default) or hours on Self-hosted IR; staging storage; per-activity-run charges.
- **Data Flows**: vCore-hours of the Spark cluster (General/Memory optimized), plus 3–5 minute cluster start per run unless a **TTL** IR keeps it warm (which then bills idle time). Small, frequent data flows are the classic cost surprise → replace with Copy + SQL/dbt.
- **Pipeline activities/orchestration**: per 1,000 runs, cheap but nonzero with high-frequency triggers and big ForEach fan-outs.
- **External activities** (Notebook, Function, Web): billed on execution hours at a low rate — long-running waits still count.
- Data movement across regions/egress; Self-hosted IR VM cost is yours.

---

## 9. Pitfalls

- Debug runs use unpublished code; triggers run **published** code — "it works in debug" usually means unpublished.
- Lookup limits (5000 rows / 4 MB / timeout) → paginate via control table or use Script activity with output.
- ForEach: no nesting (use Execute Pipeline), `batchCount` ≤ 50, variables are pipeline-global (race conditions in parallel loops — don't `Set Variable` inside a parallel ForEach).
- Copy type mapping: decimals/dates/`varchar(max)`/binary need explicit mapping; Parquet/ORC on Self-hosted IR needs a 64-bit JRE (or OpenJDK) on the IR machine.
- Default activity timeout is very long (12 h / 7 d depending on type) → set `timeout` and `retry` explicitly on Copy/Web/Notebook.
- Tumbling window `maxConcurrency` + source contention; schedule trigger time zone is UTC unless set.
- Self-hosted IR: keep auto-update on, 2+ nodes for HA, watch concurrent jobs limit per node; it can't be shared across factories without linking.
- Managed VNet Azure IR has startup latency and interactive-authoring session cost; enable it deliberately.
- Dynamic content escaping: quotes inside SQL strings, `@` in passwords/JSON bodies (`@@`), `\n` handling — test with Set Variable before wiring into Copy.
- Data Flow and Copy sinks to ADLS produce many small files with parallel copies; set `maxRowsPerFile`/file name pattern or compact downstream.
- ADF cannot easily branch on activity *output* inside a Data Flow; put branching in the pipeline.
- Monitoring retention is 45 days; ship run logs to Log Analytics (diagnostic settings) for history and alerting.
