-- smoke: scan counters of every user table in scope, read before and after the tool calls.
-- The acceptance rule is that the tools never move them. Reads a statistics view, not the tables.
-- $1 = schemas in scope (text[])
select
     s.schemaname                                                               _schema
    ,s.relname                                                                  _name
    ,coalesce(s.seq_scan, 0)::float8                                            _seq_scan
    ,coalesce(s.seq_tup_read, 0)::float8                                        _seq_tup_read
    ,coalesce(s.idx_scan, 0)::float8                                            _idx_scan
    ,coalesce(s.idx_tup_fetch, 0)::float8                                       _idx_tup_fetch
from pg_catalog.pg_stat_user_tables s
where 1=1
    and s.schemaname = any($1::text[])
order by s.schemaname, s.relname
