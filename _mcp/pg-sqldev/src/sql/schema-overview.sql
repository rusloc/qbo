-- schema_overview: every relation in the schemas in scope, one row each.
-- Catalog only: pg_class, pg_namespace, pg_index, pg_inherits, pg_stat_user_tables.
--
-- No size function is called. pg_total_relation_size() takes a lock on the relation and would
-- stall behind a non-concurrent materialized view refresh. Sizes here are relpages * block_size,
-- as of the last vacuum / analyze: heap + toast + indexes, and for a partitioned parent the sum
-- of its direct partitions.
-- $1 = schemas in scope (text[])
with _rel as (
    select
         c.oid                                                                  _oid
        ,n.nspname                                                              _schema
        ,c.relname                                                              _name
        ,c.relkind::text                                                        _kind
        ,c.relispartition                                                       _is_partition
        ,case
             when c.reltuples < 0
                 then null
             else c.reltuples::float8
         end                                                                    _rows
        ,c.relpages::float8
             + coalesce(t.relpages, 0)
             + coalesce(i._index_pages, 0)                                      _pages
    from pg_catalog.pg_class c
    join pg_catalog.pg_namespace n on n.oid = c.relnamespace
    left join pg_catalog.pg_class t on t.oid = c.reltoastrelid
    left join lateral (
        select
             sum(x.relpages)::float8                                            _index_pages
        from pg_catalog.pg_index d
        join pg_catalog.pg_class x on x.oid = d.indexrelid
        where 1=1
            and d.indrelid = c.oid
    ) i on true
    where 1=1
        and n.nspname = any($1::text[])
        and c.relkind in ('r', 'p', 'v', 'm', 'f')
)
select
     r._schema                                                                  _schema
    ,r._name                                                                    _name
    ,r._kind                                                                    _kind
    ,r._is_partition                                                            _is_partition
    ,case
         when r._kind = 'p' and r._rows is null
             then k._child_rows
         else r._rows
     end                                                                        _est_rows
    ,(r._pages + coalesce(k._child_pages, 0))
         * current_setting('block_size')::int                                   _est_bytes
    ,to_char(greatest(s.last_analyze, s.last_autoanalyze), 'YYYY-MM-DD')        _last_analyze
    ,coalesce(k._partitions, 0)                                                 _partitions
    ,has_table_privilege(r._oid, 'select')                                      _can_select
    ,obj_description(r._oid, 'pg_class')                                        _comment
-- #if citus
    ,case
         when p.partmethod = 'h'
             then 'distributed'
         when p.partmethod in ('a', 'r')
             then 'distributed (append/range)'
         when p.partmethod = 'n' and p.repmodel = 't'
             then 'reference'
         when p.partmethod = 'n'
             then 'local (citus managed)'
     end                                                                        _citus_type
-- #else
    ,null::text                                                                 _citus_type
-- #endif
from _rel r
left join pg_catalog.pg_stat_user_tables s on s.relid = r._oid
left join lateral (
    select
         count(*)::int                                                          _partitions
        ,sum(c._pages)                                                          _child_pages
        ,sum(c._rows)                                                           _child_rows
    from pg_catalog.pg_inherits h
    left join _rel c on c._oid = h.inhrelid
    where 1=1
        and h.inhparent = r._oid
) k on true
-- #if citus
left join pg_dist_partition p on p.logicalrelid = r._oid
-- #endif
where 1=1
order by r._schema, r._name
