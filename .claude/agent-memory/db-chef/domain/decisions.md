<!-- next-id: DEC-002 -->

# Decisions

### DEC-001 · Advisory xact lock, not `for update`, for the Vault token single-flight · 2026-09-25
**Decision:** `qbo.refresh_token_lock()` / `qbo.refresh_token_store()` serialize with `pg_advisory_xact_lock(hashtext('qbo_refresh_token'))` instead of `select ... from vault.secrets for update`.
**Context:** Supabase's own `supabase_vault/after-create.sql` grants `postgres` only `select, delete, truncate, references` on `vault.secrets` / `vault.decrypted_secrets` (plus `execute` on `create_secret`, `update_secret`). Every SQL locking clause (`for update`, `for share`, ...) needs `UPDATE` privilege, so the row lock would fail at first ETL run with `permission denied for table secrets`, also through the view. `lock table ... share update exclusive` would work with `delete`/`truncate` but puts a table-level lock on a table the other app shares (ADR-0008). Advisory lock = zero footprint on `vault.*`, transaction-scoped, reentrant in-session. ADR-0007's guarantee (single-flight refresh, lock released on commit) is preserved; only the mechanism changed.
**Reversibility:** high — 2 lines per function; swap back if `has_table_privilege('postgres', 'vault.secrets', 'update')` ever returns true.
**Applied at:** `supabase/migrations/20260925214200_qbo_token_vault.sql` (file written; not yet applied to `vosk.dev`)
**Hits:** 1
**Tags:** vault, security-definer, locking, advisory-lock, token, supabase-grants
**Confidence:** high
**Last-verified:** 2026-09-25
**Trigger to revisit:** Supabase changes the `postgres` grants on `vault.secrets`; or the ETL moves the token out of Vault (ADR-0007 fallback); or a second QBO realm needs its own lock key (then key = `hashtext('qbo_refresh_token_' || realm)`).
**Related:** LSN-001
**Status:** active
