---
name: data-engineer-py
description: Python-first data engineering for the modern ELT stack — Python pipelines (Polars/pandas/PyArrow/DuckDB, SQLAlchemy, pydantic, uv), dbt (Core 1.x and Fusion 2.x), Apache Airflow 3, and three managed cloud ETL/ELT tools (Fivetran, Airbyte, Azure Data Factory). Use whenever the user wants to design, build, review, debug or optimize a data pipeline, ETL/ELT job, ingestion, DAG, dbt model, incremental load, CDC feed, backfill, data-quality check or warehouse load — even if they only say "move data from X to Y", "schedule this script", "load this API into the warehouse", "my DAG is stuck", or paste pipeline/DAG/dbt code and ask "what's wrong". Also trigger for tool-selection questions (Fivetran vs Airbyte vs ADF, dbt vs pandas, Airflow vs cron, Polars vs pandas). Defer to `dbt-fabric-warehouse` when the dbt target is Microsoft Fabric and to `pg-sql-dev` for pure PostgreSQL tuning; apply `sql-style-formatter`/`dax-sql-formatter` to any SQL emitted.
---

# Data Engineer (Python)

Opinionated guidance for building production data pipelines in Python. This file is deliberately short: it tells you *which* reference to load. Each reference is self-contained; load only what the task needs, and load it **before** writing code, because the references hold version-specific rules (Airflow 3 vs 2, dbt Core vs Fusion, provider import paths) that differ from older training data.

## 1. Triage the request → load references

| The user wants… | Load | Then |
|---|---|---|
| A Python extract/load script, dataframe transform, connector, CLI, project layout, tests | `references/python-stack.md` | + `pipeline-patterns.md` if it loads into a warehouse or runs on a schedule |
| Incremental loads, CDC, idempotency, backfills, partitioning, file formats, data quality, schema drift | `references/pipeline-patterns.md` | |
| Anything dbt: models, sources, tests, snapshots, incremental strategies, macros, CI, running dbt from Python/Airflow | `references/dbt.md` | If target is Microsoft Fabric → use skill `dbt-fabric-warehouse` instead |
| Anything Airflow: DAGs, scheduling, assets, sensors, dynamic mapping, testing, deployment, 2→3 migration | `references/airflow.md` | + the tool reference for any operator you call (dbt, Fivetran, Airbyte, ADF) |
| Managed connector ingestion, "just sync Salesforce/Postgres/Shopify to the warehouse" | `references/cloud-etl-fivetran.md` **or** `references/cloud-etl-airbyte.md` | Selection guide in §3 below |
| Azure-native pipelines, Copy activity, Self-hosted IR, Fabric Data Factory | `references/cloud-etl-adf.md` | |
| "Which tool should I use?" | §3 below, then the two candidate references | |

When the request spans layers (typical: Fivetran/Airbyte → raw, dbt → marts, Airflow orchestrating both), load each layer's reference; the integration snippets live in the *tool's* reference under "Orchestrate from Airflow".

## 2. Non-negotiable defaults (apply every time)

1. **ELT, not ETL.** Land raw data unchanged (Parquet or raw warehouse schema), transform in the warehouse with dbt. Python does extraction, loading, and the transforms SQL can't do well.
2. **Every run is idempotent and re-runnable for an interval.** A task is a pure function of `(data_interval_start, data_interval_end, config)`; re-running it overwrites the same partition or merges on keys. Never `INSERT` blindly.
3. **Incremental by default.** Watermark/cursor or CDC with a lookback window; full refresh only when explicitly justified.
4. **Explicit schemas at boundaries.** pydantic models or Polars/pandera schemas for inbound records; explicit casts in dbt staging models. `SELECT *` from a raw source is a bug waiting for a schema drift.
5. **Secrets come from the environment or a secret store**, never from code, `.env` committed to git, or Airflow Variables holding passwords.
6. **Tests ship with the code**: pytest for Python, dbt tests/unit tests for models, an import-error test for DAGs, row-count/freshness checks in production.
7. **Modern Python**: 3.12+, `uv` + `pyproject.toml`, `ruff`, type hints, `src/` layout, Polars first / pandas when the ecosystem needs it, PyArrow for interchange, DuckDB for local SQL.
8. **Versions matter.** Airflow 3.x (2.x is EOL since Apr 2026), dbt Core 1.12 / dbt Fusion 2.x, provider packages with changed import paths. When you can't see the installed version, ask or add a `# verify against installed version` note rather than guessing from memory.

## 3. Tool selection (one-line rules; details in the references)

- **Fivetran**: fastest path to reliable SaaS/database ingestion when budget allows consumption pricing and connectors exist; zero ops; extend with the Python Connector SDK. Choose for "we need Salesforce + HubSpot + Postgres in Snowflake by Monday".
- **Airbyte**: open-source or Cloud; largest long tail of connectors, build your own in the Connector Builder / low-code CDK / Python CDK; **PyAirbyte** lets you run connectors inside a Python pipeline with no platform. Choose when self-hosting, custom APIs, or cost control matter.
- **Azure Data Factory / Fabric Data Factory**: the Azure-native choice for on-prem → cloud (Self-hosted IR), metadata-driven copy at scale, and teams already in Fabric/Synapse. Choose when the estate is Microsoft.
- **Plain Python (+ Airflow)**: internal APIs, odd file formats, anything the managed tools can't reach, or when the volume is small and a 60-line script beats a vendor.
- **dbt** owns all in-warehouse transformation regardless of the ingestion tool. **Airflow** owns scheduling, dependencies, retries and alerting across all of the above.

## 4. Working procedure

1. **Establish context** (ask only for what is missing): source(s) and destination, volume and growth, required freshness, existing orchestration, cloud, Python/Airflow/dbt versions in use, how it will be deployed.
2. **Choose the layer split** using §3 and say it in one sentence ("Airbyte lands raw → dbt builds marts → Airflow schedules both").
3. **Load the references** for every layer touched. Follow their conventions (naming, folder layout, config style) rather than inventing new ones.
4. **Produce runnable artifacts**: project skeleton (`pyproject.toml`, `src/`, `tests/`, `dags/`, `dbt/`), code with type hints and docstrings, a `README` snippet with the exact commands to run locally, and tests. For more than ~10 lines of code, create files rather than inline snippets.
5. **Validate what you can**: run `ruff` and `pytest` in the sandbox, `python -c "import dag_module"` for DAG parse errors, `dbt parse` when a dbt project is present.
6. **Hand-off notes**: list environment variables/connections to create, one-time setup (e.g. enabling logical replication, Fivetran connector creation), and the first-run/backfill command.

## 5. Reference index

- `references/python-stack.md` — tooling, libraries, project layout, connectivity, config, logging, testing, performance.
- `references/pipeline-patterns.md` — idempotency, incremental/CDC, partition layouts, Parquet, backfills, retries, data quality, schema drift, observability.
- `references/dbt.md` — dbt Core 1.x vs Fusion 2.x, project conventions, materializations and incremental strategies (incl. microbatch), snapshots, tests/unit tests/contracts, Python models, programmatic runs, Airflow integration (Cosmos), CI.
- `references/airflow.md` — Airflow 3 authoring (Task SDK, assets, dynamic mapping, deferrables), config/connections, testing, deployment, 2→3 migration checklist, common failure modes.
- `references/cloud-etl-fivetran.md` — connector model, sync behaviour and system columns, REST API from Python, Connector SDK, Airflow provider, dbt packages, cost pitfalls.
- `references/cloud-etl-airbyte.md` — OSS vs Cloud, sync modes and destination tables, Connector Builder / low-code / Python CDK, PyAirbyte, public API, Airflow provider, pitfalls.
- `references/cloud-etl-adf.md` — ADF & Fabric Data Factory building blocks, metadata-driven and incremental patterns, expression language, Python SDK, Airflow provider, CI/CD, cost and behaviour pitfalls.
