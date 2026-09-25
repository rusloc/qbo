# ADR-0004 — Daily ETL run: Windows Task Scheduler on the USER's PC

- **Status:** Accepted (USER, 2026-09-25)
- **Related:** ADR-0007 (refresh token in Vault), ADR-0009 (ferry owns the ETL)

## Context

Spec §4 P1: `qbo_sync cdc` runs daily; `backfill` runs on demand.
Options weighed on 2026-09-25:

| Option | Note |
|---|---|
| GitHub Actions cron | Free at this size, Linux runner, secrets in GitHub; start time can slip |
| Azure Functions timer | Python supported, in the USER's Azure tenant; more setup, billed |
| **Windows Task Scheduler** (chosen) | Zero setup and no cloud cost; runs only while this PC is on |
| Supabase `pg_cron` | Runs SQL only; cannot run the Python ETL |

Airflow, Fivetran, Airbyte and Azure Data Factory are out: the spec's ETL is a plain Python CLI.

## Decision

- The daily `cdc` run is a Windows Task Scheduler task on the USER's PC. It runs `qbo_sync cdc` with the interpreter in `etl/.venv`, from the repo folder. ferry sets the exact command line when the CLI exists.
- Task settings:
  - "Run task as soon as possible after a scheduled start is missed", so a run skipped while the PC was off catches up.
  - "If the task is already running: Do not start a new instance". This adds single-flight on top of the Vault row lock (ADR-0007).
  - A time limit (stop the task after 1 hour).
  - Account: the USER's Windows account. "Run only when user is logged on" vs "whether logged on or not" is chosen at setup; the second option stores the Windows password with the task.
- Config comes from `etl/.env` on this PC (`CLIENT_ID`, `CLIENT_SECRET`, `REALM_ID`, `ENV`, database settings). The refresh token stays in Vault.
- Logging as in spec §4 P1: `sync_state` + JSON lines on stdout, redirected to a local, gitignored log file.
- `backfill` and `auth` run by hand.

## Consequences

- The ETL runs only while the PC is on. A gap longer than the 30-day CDC lookback (spec §1) needs a re-backfill; `qbo_sync status` shows the last successful run.
- The QBO refresh token rolls for about 100 days. After 100 days without a run it expires, and `qbo_sync auth` must be re-run.
- No secrets leave this PC, and nothing is billed. The scheduled Python runs under Windows Smart App Control; the pinned venv packages already pass (CAND-001).
- The fresh-database migration check (CI) is a separate question and is not decided here.
- **Revisit when** a client deployment needs unattended runs. GitHub Actions cron or an Azure Functions timer then run the same CLI unchanged.
