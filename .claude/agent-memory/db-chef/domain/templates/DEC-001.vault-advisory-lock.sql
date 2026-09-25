-- Template for DEC-001 — Vault secret behind security definer functions, single-flight via advisory xact lock
-- Last-tested: 2026-09-25 (libpg_query PG18 parse + plpgsql parse only; not yet applied to vosk.dev)
-- Against: Supabase Postgres 17 / supabase_vault 0.3.1 / owner = postgres (has select on vault.*, execute on create_secret/update_secret, NO update)
-- Assumptions: secret name is unique (vault partial unique index on name); caller runs both functions inside one transaction
-- Placeholders: <schema>, <secret_name>, <caller_role>

create function <schema>.<secret_name>_lock()
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
     _token           text;
begin
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('<secret_name>'));

    select
         d.decrypted_secret          _secret
    into _token
    from vault.decrypted_secrets d
    where 1=1
        and d.name = '<secret_name>';

    return _token;                   -- null until first store
end;
$$;

create function <schema>.<secret_name>_store(p_token text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
     _secret_id       uuid;
begin
    if p_token is null or p_token = '' then
        raise exception '<schema>.<secret_name>_store: empty token rejected';
    end if;

    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('<secret_name>'));

    select
         s.id                        _secret_id
    into _secret_id
    from vault.secrets s
    where 1=1
        and s.name = '<secret_name>';

    if _secret_id is null then
        perform vault.create_secret(p_token, '<secret_name>', '<description>');
    else
        perform vault.update_secret(_secret_id, p_token);
    end if;
end;
$$;

revoke execute
    on function <schema>.<secret_name>_lock()
               ,<schema>.<secret_name>_store(text)
    from public;

grant execute
    on function <schema>.<secret_name>_lock()
               ,<schema>.<secret_name>_store(text)
    to <caller_role>;

-- Negative checks after apply (read-only):
--   set role <other_role>; select <schema>.<secret_name>_lock();          -- expect: permission denied for function
--   select has_table_privilege('postgres', 'vault.secrets', 'update');    -- expect: false (if true, a row lock becomes an option again)
