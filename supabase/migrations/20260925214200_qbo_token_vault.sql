-- 20260925214200_qbo_token_vault
-- F-05 M5 | ADR-0007 (refresh token in Supabase Vault, single-flight rotation) | ADR-0003 (security definer owned by postgres, execute to qbo_etl only)
-- Two security definer functions give qbo_etl locked read / rotate access to the Vault secret qbo_refresh_token without any direct grant on schema vault.

create function qbo.refresh_token_lock()
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
     _token           text;
begin
    -- single-flight guard, held until the caller's commit / rollback (call inside the ETL transaction).
    -- advisory lock instead of "for update" on vault.secrets: on Supabase the postgres role holds no update privilege there.
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('qbo_refresh_token'));

    select
         d.decrypted_secret          _refresh_token
    into _token
    from vault.decrypted_secrets d
    where 1=1
        and d.name = 'qbo_refresh_token';

    return _token;                   -- null until qbo_sync auth stores the first token
end;
$$;

create function qbo.refresh_token_store(p_token text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
     _secret_id       uuid;
begin
    if p_token is null or p_token = '' then
        raise exception 'qbo.refresh_token_store: empty token rejected';
    end if;

    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('qbo_refresh_token'));

    select
         s.id                        _secret_id
    into _secret_id
    from vault.secrets s
    where 1=1
        and s.name = 'qbo_refresh_token';

    if _secret_id is null then
        perform vault.create_secret(p_token, 'qbo_refresh_token', 'QBO P&L: Intuit OAuth refresh token, rotates on every use (ADR-0007).');
    else
        perform vault.update_secret(_secret_id, p_token);
    end if;
end;
$$;

comment on function qbo.refresh_token_lock()      is 'QBO P&L: takes the qbo_refresh_token single-flight lock for the current transaction and returns the decrypted token (null if not stored yet). Call inside the ETL transaction (ADR-0007).';
comment on function qbo.refresh_token_store(text) is 'QBO P&L: stores the rotated refresh token in Vault (creates the secret on first use). Same transaction as refresh_token_lock (ADR-0007).';

revoke execute
    on function qbo.refresh_token_lock()
               ,qbo.refresh_token_store(text)
    from public;

grant execute
    on function qbo.refresh_token_lock()
               ,qbo.refresh_token_store(text)
    to qbo_etl;
