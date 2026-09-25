-- probe: per schema and relation kind, what the role may read and how fresh the statistics are.
-- Decides whether column_profile has to move forward (poor statistics coverage) and whether the
-- read-only role is granted correctly (selectable vs relations).
-- Catalog and statistics views only.
-- $1 = schemas in scope (text[])
select
     n.nspname                                                                  _schema
    ,c.relkind::text                                                            _kind
    ,count(*)::int                                                              _relations
    ,count(*) filter (where has_table_privilege(c.oid, 'select'))::int          _selectable
    ,count(*) filter (where c.relkind in ('r', 'm', 'p')
                        and c.reltuples < 0)::int                               _never_analyzed
    ,count(*) filter (where greatest(s.last_analyze, s.last_autoanalyze)
                            >= now() - interval '7 days')::int                  _analyzed_last_7d
    ,count(*) filter (where greatest(s.last_analyze, s.last_autoanalyze)
                            < now() - interval '30 days')::int                  _analyzed_older_30d
    ,count(*) filter (where t._tablename is not null)::int                      _with_column_stats
    -- An empty table has no pg_stats rows by nature. Only a non-empty one without them is a gap.
    ,count(*) filter (where c.relkind in ('r', 'm', 'p')
                        and c.reltuples > 0)::int                               _nonempty
    ,count(*) filter (where c.relkind in ('r', 'm', 'p')
                        and c.reltuples > 0
                        and t._tablename is null)::int                          _nonempty_without_stats
    ,coalesce(sum(c.reltuples) filter (where c.reltuples > 0), 0)::float8       _est_rows_total
    ,coalesce(max(c.reltuples), 0)::float8                                      _est_rows_largest
from pg_catalog.pg_class c
join pg_catalog.pg_namespace n on n.oid = c.relnamespace
left join pg_catalog.pg_stat_user_tables s on s.relid = c.oid
left join (
    select
         p.schemaname                                                           _schemaname
        ,p.tablename                                                            _tablename
    from pg_catalog.pg_stats p
    where 1=1
        and p.schemaname = any($1::text[])
    group by p.schemaname, p.tablename
) t on t._schemaname = n.nspname
    and t._tablename = c.relname
where 1=1
    and n.nspname = any($1::text[])
    and c.relkind in ('r', 'p', 'v', 'm', 'f')
group by n.nspname, c.relkind
order by n.nspname, c.relkind
