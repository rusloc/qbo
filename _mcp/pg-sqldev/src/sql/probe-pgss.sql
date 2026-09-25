-- probe: is pg_stat_statements readable, and does this role see the query text of others?
-- Decides whether top_queries (C4) is worth building. Fails cleanly when the view is absent.
select
     count(*)::int                                                              _statements
    ,count(*) filter (where s.query = '<insufficient privilege>')::int          _hidden_text
from pg_stat_statements s
where 1=1
