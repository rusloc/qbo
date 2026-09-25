-- probe on a Citus cluster: active nodes and shard count, from coordinator metadata only.
-- May fail for an unprivileged role; the probe records the failure and moves on.
select
     (select count(*)::int
      from pg_dist_node n
      where 1=1
          and n.isactive)                                                       _active_nodes
    ,(select count(*)::int
      from pg_dist_shard s
      where 1=1)                                                                _shards
