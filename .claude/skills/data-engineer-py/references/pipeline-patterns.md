# Pipeline patterns

Tool-agnostic design rules that every pipeline in this stack follows, whether the mover is Python, Fivetran, Airbyte or ADF and whether the transformer is dbt or Polars. Load this whenever a pipeline touches a warehouse or runs on a schedule.

## Contents
1. Layering: raw → staging → marts
2. Idempotency and load strategies
3. Incremental extraction: watermarks vs CDC
4. Files and partition layouts
5. Backfills and reprocessing
6. Reliability: retries, timeouts, rate limits, dead letters
7. Data quality gates
8. Schema drift and contracts
9. Observability and SLAs
10. Security and cost

---

## 1. Layering

```
source systems ──(extract/load, no transforms)──▶ RAW  ──(dbt staging: rename/cast/dedupe)──▶ STAGING ──(dbt intermediate + marts)──▶ MARTS ──▶ BI / ML / reverse ETL
```
- **Raw** keeps the source shape plus load metadata: `_loaded_at`, `_source_file`/`_run_id`, `_extracted_at`. Append-only or replace-by-partition; never updated in place by humans.
- **Staging** is 1:1 with raw objects: explicit column list, casts, snake_case names, dedupe on primary key + latest `updated_at`. No joins.
- **Marts** are business grain (facts/dims/aggregates). Only marts are exposed to BI.
- Python owns raw; dbt owns staging and marts. A Python transform is justified only for things SQL can't express (ML scoring, parsing binary formats, calling APIs).

---

## 2. Idempotency and load strategies

An idempotent run for interval `[start, end)` produces the same target state no matter how many times it executes. Pick one strategy per target table and document it in the model/pipeline docstring.

| Strategy | When | How |
|---|---|---|
| **Replace partition** (insert-overwrite) | Immutable event/fact data keyed by date; object storage; BigQuery/Spark/Iceberg tables | Write to `dt=<interval date>` path or partition, then atomically swap. Re-run = overwrite same partition. |
| **Merge / upsert on key** | Mutable entities (customers, orders) with a reliable primary key and `updated_at` | Load batch into a staging table → `MERGE INTO target USING stage ON key WHEN MATCHED AND stage.updated_at > target.updated_at THEN UPDATE ... WHEN NOT MATCHED THEN INSERT`. |
| **Delete + insert by interval** | Facts without a stable key but with an event timestamp | Same transaction: `DELETE FROM target WHERE event_ts >= :start AND event_ts < :end; INSERT ...` |
| **Append with run_id** | Audit logs, raw landing | Append; readers dedupe on `(key, max(_loaded_at))` in staging. Re-run cleanup = delete rows with the same `run_id` first. |
| **Full refresh** | Small dimensions (< a few million rows), reference data | Write to `target__new`, validate row count, rename swap. |

Rules:
- Bulk-load into a **staging table**, then apply the strategy in one transaction. Row-by-row upserts from Python are 100× slower and not atomic.
- Keys for merge must be **deterministic and stable**; if the source lacks one, build a surrogate hash of the natural key columns (`md5(concat_ws('|', a, b, c))`) in staging and document it.
- Soft deletes: prefer an `is_deleted`/`_deleted_at` flag over physical deletes; CDC and Fivetran/Airbyte all give you a deleted marker — carry it forward, don't drop the rows.

---

## 3. Incremental extraction

### Watermark (query-based)
```
select ... from orders
where updated_at >= :watermark - interval '30 minutes'   -- lookback
  and updated_at <  :interval_end
order by updated_at
```
- Store the watermark **after a successful load**, as the `max(updated_at)` actually loaded (not `now()`), in a control table (`etl.watermarks(pipeline, table, watermark_ts, updated_at)`) or as Airflow XCom only for very small pipelines.
- The **lookback window** covers late-arriving updates and clock skew; the merge strategy makes the overlap harmless.
- Requires an indexed, monotonically maintained `updated_at`. If the source can't guarantee that (batch jobs that backdate, missing index), use CDC or a full refresh — a silently incomplete incremental is the worst outcome.
- Hard deletes are invisible to watermark extraction. Options: periodic key-reconciliation (`select id from source` → anti-join), a deleted-rows log, or CDC.

### CDC (log-based)
- PostgreSQL logical replication (`wal_level=logical`, publication + slot, `pgoutput`), MySQL binlog, SQL Server CDC/Change Tracking, MongoDB change streams.
- Use a platform for it: Fivetran and Airbyte both do log-based CDC for the main databases; Debezium (Kafka Connect) when streaming is already in place. Writing CDC consumers in Python from scratch is rarely justified.
- CDC output is an ordered stream of `insert/update/delete` with LSN/offset; land it append-only in raw, dedupe to latest per key in staging (`row_number() over (partition by key order by lsn desc) = 1`), keep the delete marker.
- Operational rule: a replication slot that isn't consumed fills the source disk. Alert on slot lag / replication lag, and drop slots when a connector is retired.

### APIs
- Cursor pagination beats offset; incremental on `updated_since` params with the same lookback idea; persist the last cursor/`updated_at` after the load succeeds.
- Respect rate limits with `tenacity` backoff on 429/5xx, `Retry-After` when present, and a concurrency cap; partition long histories by month for initial loads and let Airflow map over them.

---

## 4. Files and partition layouts

- Landing path: `<zone>/<source>/<object>/dt=YYYY-MM-DD/[hour=HH/]part-<run_id>-<n>.parquet` (Hive-style so DuckDB, Spark, Athena, BigQuery external tables and `pyarrow.dataset` all prune partitions).
- Partition key = **the interval you re-run by**, usually the load/event date, not the business key.
- Parquet: `compression="zstd"`, explicit schema from the source contract, timestamps as `timestamp[us, tz=UTC]`, decimals as `decimal128`, never floats for money. Target 100–500 MB files; compact small files daily.
- Table formats (Iceberg/Delta) when you need ACID on object storage, time travel, or many writers; pick the one native to the platform (Delta on Databricks/Fabric, Iceberg elsewhere) and write via the platform, not via a hand-rolled writer.
- Keep raw vendor files immutable in an `archive/` prefix with the same partition layout; reprocessing then never depends on the vendor again.

---

## 5. Backfills and reprocessing

- Because `run(start, end)` is interval-driven, a backfill is just a loop over intervals: `airflow backfill create --dag-id ... --from-date ... --to-date ...` (Airflow 3) or the CLI `acme-pipelines run orders --start 2025-01-01 --end 2025-02-01 --chunk 1d`.
- Backfills use the **same code path** as scheduled runs; a separate "backfill script" drifts within a month.
- Throttle: `max_active_runs`, pools, and source-friendly hours; a full-history pull against a production OLTP database needs a replica or off-peak window.
- For dbt, reprocessing = `dbt run --full-refresh -s model` or, for microbatch models, `dbt run -s model --event-time-start ... --event-time-end ...` (see `dbt.md` §4).
- Log every backfill (who, why, interval) in the control table; it explains later anomalies.

---

## 6. Reliability

- **Timeouts on everything** (HTTP, DB statements `statement_timeout`, Airflow `execution_timeout`). A hung task is worse than a failed one.
- **Retries with jittered exponential backoff** only for transient classes (network, 429, 5xx, deadlocks). Never retry a failed validation or a bad-credentials error — it just delays the alert.
- **Dead-letter records**: rows that fail parsing/validation go to `<table>__rejects` with the error and raw payload; the batch continues; alert when the reject rate crosses a threshold. Don't fail a 10M-row load for one malformed row, and don't silently drop it either.
- **Circuit breakers** at the pipeline level: if `rows_extracted == 0` when history says it should be > 0, or if the row count drops > X% vs the trailing average, fail before loading (see §7).
- **Locks**: one run per pipeline/interval at a time (`max_active_runs=1` or a DB advisory lock) so two overlapping runs can't double-merge.

---

## 7. Data quality gates

Run checks at the boundary where fixing is cheapest:

| Where | Check | Tool |
|---|---|---|
| After extract | row count > 0 (when expected), schema matches contract, no duplicate keys in batch | Python asserts / pandera |
| After raw load | loaded count == extracted count, `_loaded_at` populated | Python asserts, warehouse query |
| Staging/marts | `unique`, `not_null`, `relationships`, `accepted_values`, freshness, volume anomalies | dbt tests, dbt `source freshness`, `dbt-expectations`, Elementary |
| Cross-system | reconciliation totals vs source (sum of amounts by day) | scheduled reconciliation model/DAG |

- Severity matters: `warn` for anomalies you want to see, `error` only for things that would poison downstream. In dbt: `config: {severity: warn}` / `error_if: ">100"`.
- Freshness: every source declares an expected cadence (`loaded_at_field` + `warn_after`/`error_after` in dbt, or a `max(_loaded_at)` check). Most "the dashboard is wrong" incidents are stale data, not wrong logic.
- Keep quality checks close to the code (dbt YAML, pytest) rather than in a separate GUI tool nobody maintains.

---

## 8. Schema drift and contracts

- Declare the expected schema for every source object (pydantic / pandera / dbt `columns:` with `data_type`). Extraction validates against it.
- **Additive changes** (new nullable column): allow through raw automatically (Fivetran/Airbyte add columns; Parquet schema evolution merges), surface a warning, and add to staging deliberately.
- **Breaking changes** (type change, removed/renamed column): fail the run at extract with a clear message; fix the contract in the same PR as the staging model.
- dbt **model contracts** (`contract: {enforced: true}`) on marts freeze the interface BI depends on; model **versions** for breaking changes to marts.
- Never let raw column order or `select *` define downstream structure.

---

## 9. Observability and SLAs

- Every run records: pipeline, interval, run_id, start/end time, rows in/out, bytes, status, error. A `etl.run_log` table is enough to start; Airflow's metadata DB is not a reporting store.
- Alerts on: failure after final retry, freshness breach, volume anomaly, reject rate, CDC slot lag. Route to the on-call channel with the run link; keep noise low or alerts get muted.
- Define an SLA per mart ("orders mart fresh by 06:00 UTC") and monitor the *mart*, not just the ingestion task; use Airflow 3 deadline alerts or a freshness DAG.
- Lineage via OpenLineage (Airflow provider, dbt integration) when the org has a catalog; otherwise `dbt docs` is the minimum.

---

## 10. Security and cost

- Least privilege: extraction users are read-only on the source (and read from a replica when possible); loading users write only to raw/staging schemas; dbt has its own role.
- PII: hash or tokenize at staging, keep raw locked down, document which columns are sensitive in dbt `meta`.
- Secrets in a secret manager / Airflow secrets backend; rotate; never in DAG code, dbt `profiles.yml` in git, or log output.
- Cost levers by tool: Fivetran = monthly active rows (avoid syncing high-churn tables you don't need); Airbyte Cloud = credits by rows/volume; ADF = DIU-hours and Data Flow vCore-hours (cluster spin-up); warehouse = bytes scanned/compute minutes (partition pruning, incremental models). Measure before optimizing, but design incremental from day one.
