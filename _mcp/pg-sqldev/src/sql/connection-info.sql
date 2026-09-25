-- connection_info / capabilities: one row describing the server, the role, the guards in force
-- and the schemas in scope. Settings and catalog only, no user table is touched.
-- $1 = schemas in scope (text[])
select
     current_setting('server_version')                                          _server_version
    ,current_setting('server_version_num')::int                                 _server_version_num
    ,current_database()                                                         _database
    ,current_user                                                               _current_role
    ,session_user                                                               _session_role
    ,(select r.rolsuper
      from pg_catalog.pg_roles r
      where 1=1
          and r.rolname = current_user)                                         _is_superuser
    ,current_setting('transaction_read_only')                                   _transaction_read_only
    ,current_setting('default_transaction_read_only')                           _default_read_only
    ,current_setting('statement_timeout')                                       _statement_timeout
    ,current_setting('lock_timeout')                                            _lock_timeout
    ,current_setting('application_name')                                        _application_name
    ,current_setting('max_connections')::int                                    _max_connections
    ,current_setting('TimeZone')                                                _timezone
    ,current_setting('server_encoding')                                         _encoding
    ,pg_is_in_recovery()                                                        _is_replica
    ,(select e.extversion
      from pg_catalog.pg_extension e
      where 1=1
          and e.extname = 'citus')                                              _citus_version
    ,(select e.extversion
      from pg_catalog.pg_extension e
      where 1=1
          and e.extname = 'pg_stat_statements')                                 _pg_stat_statements_version
    ,has_table_privilege(to_regclass('pg_dist_partition'), 'select')            _citus_metadata_readable
    ,(select
          jsonb_agg(
              jsonb_build_object(
                   'schema', u._name
                  ,'exists', n.oid is not null
                  ,'usage', coalesce(has_schema_privilege(n.oid, 'usage'), false)
              )
              order by u._ord
          )
      from unnest($1::text[]) with ordinality u(_name, _ord)
      left join pg_catalog.pg_namespace n on n.nspname = u._name)               _schemas
