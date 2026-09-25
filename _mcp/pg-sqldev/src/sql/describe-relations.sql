-- describe_table 1/2: resolve the requested names and return one row per matching relation with
-- its header facts, plus constraints (own and incoming) and indexes folded into JSON, so that a
-- batch of tables costs one query instead of one per section.
-- Catalog only. Names match case-insensitively; the caller prefers the exact match.
-- $1 = schemas in scope (text[])
-- $2 = requested schema per name, null when the name was unqualified (text[])
-- $3 = requested relation names (text[])
-- $4 = include view / materialized view definitions (boolean)
with _req as (
    select
         u._ord::int                                                            _ord
        ,u._schema                                                              _req_schema
        ,u._name                                                                _req_name
    from unnest($2::text[], $3::text[]) with ordinality u(_schema, _name, _ord)
)
select
     r._ord                                                                     _ord
    ,c.oid::bigint::float8                                                      _oid
    ,n.nspname                                                                  _schema
    ,c.relname                                                                  _name
    ,format('%I.%I', n.nspname, c.relname)                                      _qualified
    ,(c.relname = r._req_name)                                                  _exact_match
    ,c.relkind::text                                                            _kind
    ,c.relpersistence::text                                                     _persistence
    ,pg_get_userbyid(c.relowner)                                                _owner
    ,case
         when c.reltuples < 0
             then null
         else c.reltuples::float8
     end                                                                        _est_rows
    ,(c.relpages::float8 + coalesce(t.relpages, 0))
         * current_setting('block_size')::int                                   _est_table_bytes
    ,coalesce(i._index_pages, 0)
         * current_setting('block_size')::int                                   _est_index_bytes
    ,to_char(greatest(s.last_analyze, s.last_autoanalyze), 'YYYY-MM-DD HH24:MI')  _last_analyze
    ,to_char(greatest(s.last_vacuum, s.last_autovacuum), 'YYYY-MM-DD HH24:MI')  _last_vacuum
    ,has_table_privilege(c.oid, 'select')                                       _can_select
    ,obj_description(c.oid, 'pg_class')                                         _comment
    ,c.relispartition                                                           _is_partition
    ,(select format('%I.%I', m.nspname, b.relname)
      from pg_catalog.pg_inherits h
      join pg_catalog.pg_class b on b.oid = h.inhparent
      join pg_catalog.pg_namespace m on m.oid = b.relnamespace
      where 1=1
          and h.inhrelid = c.oid
      limit 1)                                                                  _parent
    ,case
         when c.relkind = 'p'
             then pg_get_partkeydef(c.oid)
     end                                                                        _partition_key
    ,(select count(*)::int
      from pg_catalog.pg_inherits h
      where 1=1
          and h.inhparent = c.oid)                                              _partitions
    ,case
         when c.relkind = 'm'
             then c.relispopulated
     end                                                                        _is_populated
    ,case
         when $4::boolean and c.relkind in ('v', 'm')
             then pg_get_viewdef(c.oid, true)
     end                                                                        _definition
    ,k._constraints                                                             _constraints
    ,i._indexes                                                                 _indexes
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
    ,case
         when p.partkey is not null
             then column_to_column_name(p.logicalrelid, p.partkey)
     end                                                                        _citus_distribution_column
    ,p.colocationid                                                             _citus_colocation_id
    ,(select count(*)::int
      from pg_dist_shard d
      where 1=1
          and d.logicalrelid = c.oid)                                           _citus_shards
-- #else
    ,null::text                                                                 _citus_type
    ,null::text                                                                 _citus_distribution_column
    ,null::int                                                                  _citus_colocation_id
    ,null::int                                                                  _citus_shards
-- #endif
from _req r
join pg_catalog.pg_namespace n
    on n.nspname = any($1::text[])
    and (r._req_schema is null or n.nspname = r._req_schema)
join pg_catalog.pg_class c
    on c.relnamespace = n.oid
    and lower(c.relname) = lower(r._req_name)
left join pg_catalog.pg_class t on t.oid = c.reltoastrelid
left join pg_catalog.pg_stat_user_tables s on s.relid = c.oid
left join lateral (
    select
         jsonb_agg(
             jsonb_build_object(
                  'name', o.conname
                 ,'type', o.contype::text
                 ,'incoming', (o.conrelid <> c.oid)
                 ,'validated', o.convalidated
                 ,'definition', pg_get_constraintdef(o.oid, true)
                 ,'from_table', (select format('%I.%I', a.nspname, b.relname)
                                 from pg_catalog.pg_class b
                                 join pg_catalog.pg_namespace a on a.oid = b.relnamespace
                                 where 1=1
                                     and b.oid = o.conrelid)
                 ,'from_columns', (select jsonb_agg(a.attname order by x._ord)
                                   from unnest(o.conkey) with ordinality x(_attnum, _ord)
                                   join pg_catalog.pg_attribute a
                                       on a.attrelid = o.conrelid
                                       and a.attnum = x._attnum)
                 ,'to_table', (select format('%I.%I', a.nspname, b.relname)
                               from pg_catalog.pg_class b
                               join pg_catalog.pg_namespace a on a.oid = b.relnamespace
                               where 1=1
                                   and b.oid = o.confrelid)
                 ,'to_columns', (select jsonb_agg(a.attname order by x._ord)
                                 from unnest(o.confkey) with ordinality x(_attnum, _ord)
                                 join pg_catalog.pg_attribute a
                                     on a.attrelid = o.confrelid
                                     and a.attnum = x._attnum)
             )
             order by (o.conrelid <> c.oid), o.contype, o.conname
         )                                                                      _constraints
    from pg_catalog.pg_constraint o
    where 1=1
        and o.contype in ('p', 'u', 'f', 'c', 'x')
        and (
               o.conrelid = c.oid
            or (o.confrelid = c.oid and o.conparentid = 0)
        )
) k on true
left join lateral (
    select
         jsonb_agg(
             jsonb_build_object(
                  'name', x.relname
                 ,'definition', pg_get_indexdef(d.indexrelid)
                 ,'is_primary', d.indisprimary
                 ,'is_unique', d.indisunique
                 ,'is_valid', d.indisvalid
                 ,'est_bytes', x.relpages::float8 * current_setting('block_size')::int
                 ,'scans', u.idx_scan
             )
             order by d.indisprimary desc, d.indisunique desc, x.relname
         )                                                                      _indexes
        ,sum(x.relpages)::float8                                                _index_pages
    from pg_catalog.pg_index d
    join pg_catalog.pg_class x on x.oid = d.indexrelid
    left join pg_catalog.pg_stat_user_indexes u on u.indexrelid = d.indexrelid
    where 1=1
        and d.indrelid = c.oid
) i on true
-- #if citus
left join pg_dist_partition p on p.logicalrelid = c.oid
-- #endif
where 1=1
    and c.relkind in ('r', 'p', 'v', 'm', 'f')
order by r._ord, (c.relname = r._req_name) desc, n.nspname
