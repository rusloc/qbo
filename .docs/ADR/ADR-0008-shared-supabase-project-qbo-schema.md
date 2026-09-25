# ADR-0008 — Shared Supabase project `vosk.dev`; QBO in its own schema

- **Status:** Accepted (USER, 2026-09-25)
- **Supersedes:** `CLAUDE.md` tenancy rule "one client (QBO realm) per deployment — one Supabase project per client"
- **Related:** ADR-0001 (warehouse), ADR-0003 (schema layout, Data API exposure, DB roles — open)

## Context

The warehouse project `vosk.dev` (ADR-0001) is the USER's personal web-app backend, and its functionality will grow.
A read-only check through the Supabase MCP on 2026-09-25 found another app already there: 8 migrations (`lead_engine_init` … `schedule_digest`, 3 of them pg_cron schedules), schemas `public` (7 tables, 1 view), `demo_sales` (4 tables) and `private`, and extensions `pg_cron` and `pg_net`.
`CLAUDE.md` said one Supabase project per client. The USER dropped that rule: QBO shares the project and gets its own schema.

## Decision

- QBO shares `vosk.dev` with the USER's other backends.
- Every QBO object lives in a dedicated QBO schema namespace. Spec §2 table names stay exactly as written, schema-qualified. The spec fixes no schema, so this is not a spec delta.
- The namespace name and layout (one `qbo` schema, or one `qbo_*` schema per layer with only the serve schema exposed) are decided in ADR-0003.
- Objects without a schema (roles, pg_cron job names) take a `qbo_` prefix.
- QBO work never creates, alters, grants on or drops anything outside its namespace. Project-wide settings (Data API exposed schemas, extensions, auth, network restrictions) are shared and change only after the USER confirms.
- One QBO realm per deployment; multi-entity consolidation stays a non-goal.

## Consequences

- **Shared migration history.** `supabase_migrations.schema_migrations` already holds the other app's 8 migrations. `supabase db push` from this repo stops on remote versions it does not have locally. The fix the CLI suggests (`supabase migration repair`) would rewrite the other app's history. The QBO apply path must be decided before the first migration. Options: (a) one migrations folder for the whole `vosk.dev` backend, with QBO migrations in it; (b) QBO migrations applied by a runner that keeps its own history table inside the QBO namespace.
- The gate "every migration applies cleanly on a fresh database" still holds, run on a disposable database and never on `vosk.dev`.
- The Data API exposed-schemas list is project-wide: adding the QBO serve schema changes a shared setting. No QBO raw / stg / mart object may be reachable through it.
- Compute, connections, storage and backups are shared: a restore or PITR of `vosk.dev` rolls back every app in it, and QBO backfills compete with the other app for resources.
- Credentials that reach QBO (the `postgres` role, the `service_role` key, the Supabase MCP) also reach the other app's data. The Supabase MCP should run with `read_only=true`. The QBO ETL and Power BI get their own `qbo_` roles, scoped to the QBO namespace (ADR-0003).
