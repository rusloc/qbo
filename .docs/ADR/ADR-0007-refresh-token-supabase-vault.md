# ADR-0007 — QBO refresh token in Supabase Vault

- **Status:** Accepted (USER, 2026-09-25): Supabase **Vault** is the primary store. The USER first said "Supabase env vars" and accepts another store if Vault falls short.
- **Related:** ADR-0003 (schema `qbo`, role `qbo_etl`), ADR-0008 (shared project)

## Context

Spec §1: the QBO refresh token rotates on every use. The new token must be persisted atomically (DB transaction + row lock) before it is used, and refreshes must never run concurrently.
Supabase has two places that could be called "env vars":

| Store | Readable by | Updated how | Meets spec §1? |
|---|---|---|---|
| Edge Function secrets (`supabase secrets set`) | Edge Functions only (`Deno.env`) | dashboard / CLI / Management API, outside any DB transaction | **No.** No row lock or atomic write. The Python ETL cannot read them without an extra function hop. Every rotation needs a Management API token, a second long-lived and very powerful secret. |
| **Vault** (`vault.secrets`, extension `supabase_vault`, already installed in `vosk.dev`) | Postgres, through `vault.decrypted_secrets` | `vault.update_secret()`, inside the ETL's own transaction | **Yes.** Encrypted at rest; lock, read and update happen in one transaction. |

## Decision

- The refresh token lives in Vault as the secret `qbo_refresh_token` (the `qbo_` prefix follows ADR-0008).
- `qbo_etl` gets no direct Vault access. Two `security definer` functions in `qbo` (owner `postgres`, `set search_path = ''`, `execute` granted to `qbo_etl` only):
  - `qbo.refresh_token_lock()` → `text`: locks the secret's row and returns the current token. It must be called inside the ETL's transaction.
  - `qbo.refresh_token_store(text)`: writes the rotated token.
- ETL flow: `begin` → `refresh_token_lock()` → POST the refresh to Intuit → `refresh_token_store(new)` → `commit` → then use the access token. The row lock makes refreshes single-flight.
- The access token (1 h TTL) stays in memory only.
- `qbo_sync auth` stores the first token through `refresh_token_store`.
- `CLIENT_ID`, `CLIENT_SECRET` and `REALM_ID` do not rotate. They stay in env: `.env` locally, CI / runner secrets later (ADR-0004).

## Consequences

- One more migration (functions + grants): M5 in F-05.
- Privileged roles of the shared project (`postgres`, `service_role`) can read the token. That is accepted: it is the same trust boundary as the rest of `vosk.dev`.
- If the commit fails after Intuit has issued a new token, the stored token is stale. Recovery: re-run `qbo_sync auth`.
- The token never appears in the repo, logs or fixtures (spec §9.1).
