# ADR-0001 — Supabase Postgres is the warehouse

- **Status:** Accepted (USER, 2026-09-25)
- **Supersedes:** spec §0 "PostgreSQL or Azure SQL (parameterize; support both)"

## Context

The spec (`.docs/qbo-pnl-project-spec.md` §0) asks for a warehouse on PostgreSQL *or* Azure SQL, parameterized for both.
The USER has decided that the warehouse lives in Supabase, and that it feeds two consumers: the Power BI model and a React online report.

## Decision

- The warehouse is a Supabase project (managed PostgreSQL). The Azure SQL path is dropped.
- Spec §2 DDL is implemented in the PostgreSQL dialect only: `jsonb` payloads, `numeric(15,2)` amounts, `generated always as identity` keys, `timestamptz` for sync timestamps.
- All DDL is versioned as Supabase CLI migrations in `supabase/migrations/`.
- Both consumers read the serve layer (`vw_*`) only.

## Consequences

- One engine to test; no dialect abstraction in the ETL or the transforms.
- The React report can read the serve views through the Supabase Data API. The Data API makes schema exposure and RLS a security concern the spec did not have (ADR-0003).
- Windows clients connect through the Supabase session pooler (IPv4); the direct host is IPv6-only without the IPv4 add-on.
- Power BI connects with the built-in PostgreSQL connector. How the Power BI Service refreshes (cloud connection or gateway) is still open (ADR-0006).
- The spec text in §0, §2 ("adapt types per engine") and §4 Phase 4 ("Server, Database" parameters) remains valid; only the Azure SQL option is gone. A spec amendment should record this.
