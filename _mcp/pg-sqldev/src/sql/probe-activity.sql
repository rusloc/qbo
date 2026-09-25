-- probe / smoke: connection headroom and our own footprint. One statistics view, no user table.
-- Sessions of other roles show NULL in most columns for an unprivileged role; counting rows still works.
-- $1 = application name of the MCP server sessions (text)
select
     count(*)::int                                                              _sessions
    ,count(*) filter (where a.state = 'active')::int                            _active
    ,count(*) filter (where a.state like 'idle in transaction%')::int           _idle_in_transaction
    ,count(*) filter (where a.application_name = $1::text)::int                 _mcp_sessions
    ,count(*) filter (where a.backend_type = 'client backend')::int             _client_backends
    -- Sessions that are not this one and could be client sessions. An unprivileged role sees NULL
    -- backend_type on other roles' sessions, so NULL counts as "could be": the conservative reading.
    ,count(*) filter (where a.pid <> pg_backend_pid()
                        and coalesce(a.backend_type, 'client backend') = 'client backend')::int   _other_sessions
from pg_catalog.pg_stat_activity a
where 1=1
