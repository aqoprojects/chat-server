-- ── Unused indexes (candidates for removal) ───────────────────────────────────
-- An index that has never been scanned since the last pg_stat_reset()
-- is wasting disk space and slowing down writes.
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
WHERE idx_scan = 0
  AND schemaname = 'public'
ORDER BY pg_relation_size(indexrelid) DESC;

-- ── Sequential scans on large tables (missing indexes) ───────────────────────
-- A table with many seq_scan and large n_live_tup likely needs a new index.
SELECT
    relname AS table_name,
    seq_scan,
    seq_tup_read,
    idx_scan,
    n_live_tup,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables
WHERE schemaname = 'public'
  AND n_live_tup > 10000    -- only large tables
ORDER BY seq_scan DESC;

-- ── Index bloat (indexes that need REINDEX) ───────────────────────────────────
-- Indexes accumulate dead tuples after heavy UPDATE/DELETE workloads.
-- Schedule REINDEX CONCURRENTLY on indexes with bloat_ratio > 30%.
SELECT
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY pg_relation_size(indexrelid) DESC
LIMIT 20;

-- ── Slowest queries (requires pg_stat_statements extension) ──────────────────
-- Identifies queries that need index attention.
-- Enable with: CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SELECT
    LEFT(query, 100) AS query_preview,
    calls,
    round(total_exec_time::numeric, 2) AS total_ms,
    round(mean_exec_time::numeric, 2) AS mean_ms,
    round(stddev_exec_time::numeric, 2) AS stddev_ms,
    rows
FROM pg_stat_statements
WHERE query NOT ILIKE '%pg_stat%'
ORDER BY mean_exec_time DESC
LIMIT 20;