-- connection_info on a Citus cluster: how many tables are distributed, reference, or local.
-- Reads coordinator metadata only (pg_dist_partition). It does not contact the workers.
-- Deliberately NOT citus_tables: that view computes table sizes by fanning out to every worker.
select
     count(*) filter (where p.partmethod = 'h')::int                            _distributed_tables
    ,count(*) filter (where p.partmethod in ('a', 'r'))::int                    _append_range_tables
    ,count(*) filter (where p.partmethod = 'n' and p.repmodel = 't')::int       _reference_tables
    ,count(*) filter (where p.partmethod = 'n' and p.repmodel <> 't')::int      _local_managed_tables
from pg_dist_partition p
where 1=1
