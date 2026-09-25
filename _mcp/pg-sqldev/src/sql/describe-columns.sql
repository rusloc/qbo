-- describe_table 2/2: columns of the resolved relations with their planner statistics.
-- Catalog only: pg_attribute, pg_attrdef, pg_stats. pg_stats shows a column only when the role
-- may select it, so missing statistics can mean "never analyzed" or "no privilege".
-- most_common_vals holds real data values. Only the top five are read.
-- $1 = relation oids (bigint[])
select
     a.attrelid::bigint::float8                                                 _oid
    ,a.attnum::int                                                              _position
    ,a.attname                                                                  _column
    ,format_type(a.atttypid, a.atttypmod)                                       _type
    ,a.attnotnull                                                               _not_null
    ,pg_get_expr(d.adbin, d.adrelid)                                            _default
    ,a.attidentity::text                                                        _identity
    ,a.attgenerated::text                                                       _generated
    ,col_description(a.attrelid, a.attnum)                                      _comment
    ,s.null_frac::float8                                                        _null_frac
    ,s.n_distinct::float8                                                       _n_distinct
    ,s.avg_width::int                                                           _avg_width
    ,s.correlation::float8                                                      _correlation
    ,to_jsonb((s.most_common_vals::text::text[])[1:5])                          _top_values
    ,to_jsonb((s.most_common_freqs)[1:5])                                       _top_freqs
from pg_catalog.pg_attribute a
join pg_catalog.pg_class c on c.oid = a.attrelid
join pg_catalog.pg_namespace n on n.oid = c.relnamespace
left join pg_catalog.pg_attrdef d
    on d.adrelid = a.attrelid
    and d.adnum = a.attnum
left join pg_catalog.pg_stats s
    on s.schemaname = n.nspname
    and s.tablename = c.relname
    and s.attname = a.attname
    and s.inherited = (c.relkind = 'p')
where 1=1
    and a.attrelid = any($1::bigint[]::oid[])
    and a.attnum > 0
    and not a.attisdropped
order by a.attrelid, a.attnum
