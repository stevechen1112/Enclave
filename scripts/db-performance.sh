#!/usr/bin/env bash
# ===========================================================================
# Enclave 資料庫效能分析腳本（T4-15）
# ===========================================================================
#
# 用途：
#   1. 開啟 PostgreSQL slow query log
#   2. 對常用查詢執行 EXPLAIN ANALYZE
#   3. 檢查索引使用狀況
#   4. 輸出效能報告
#
# 使用方式：
#   chmod +x scripts/db-performance.sh
#   ./scripts/db-performance.sh
#
# 環境變數：
#   PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE
# ===========================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
DB_HOST="${PGHOST:-localhost}"
DB_PORT="${PGPORT:-5432}"
DB_USER="${PGUSER:-enclave}"
DB_NAME="${PGDATABASE:-enclave}"

PSQL_CMD="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME"
REPORT_DIR="reports/db-performance"
REPORT_FILE="${REPORT_DIR}/report_$(date +%Y%m%d_%H%M%S).txt"

mkdir -p "$REPORT_DIR"

echo "======================================================================"
echo "📊 Enclave 資料庫效能分析"
echo "      Host: ${DB_HOST}:${DB_PORT}"
echo "      Database: ${DB_NAME}"
echo "      Report: ${REPORT_FILE}"
echo "======================================================================"

# ---------------------------------------------------------------------------
# 1. 資料庫大小與表格統計
# ---------------------------------------------------------------------------
echo ""
echo "=== 1. 資料庫大小與表格統計 ===" | tee -a "$REPORT_FILE"

$PSQL_CMD -c "
SELECT
    schemaname AS schema,
    relname AS table,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
    pg_size_pretty(pg_relation_size(relid)) AS data_size,
    pg_size_pretty(pg_indexes_size(relid)) AS index_size,
    n_live_tup AS live_rows,
    n_dead_tup AS dead_rows,
    CASE WHEN n_live_tup > 0
         THEN round(100.0 * n_dead_tup / n_live_tup, 2)
         ELSE 0 END AS dead_pct
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
" 2>/dev/null | tee -a "$REPORT_FILE"

# ---------------------------------------------------------------------------
# 2. 索引使用率
# ---------------------------------------------------------------------------
echo "" | tee -a "$REPORT_FILE"
echo "=== 2. 索引使用率 ===" | tee -a "$REPORT_FILE"

$PSQL_CMD -c "
SELECT
    schemaname,
    relname AS table,
    indexrelname AS index,
    pg_size_pretty(pg_relation_size(indexrelid)) AS size,
    idx_scan AS scans,
    idx_tup_read AS tuples_read,
    idx_tup_fetch AS tuples_fetched
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;
" 2>/dev/null | tee -a "$REPORT_FILE"

# ---------------------------------------------------------------------------
# 3. 未使用的索引（可能可刪除）
# ---------------------------------------------------------------------------
echo "" | tee -a "$REPORT_FILE"
echo "=== 3. 未使用的索引（idx_scan = 0）===" | tee -a "$REPORT_FILE"

$PSQL_CMD -c "
SELECT
    schemaname,
    relname AS table,
    indexrelname AS index,
    pg_size_pretty(pg_relation_size(indexrelid)) AS size,
    idx_scan AS scans
FROM pg_stat_user_indexes
WHERE idx_scan = 0
  AND schemaname = 'public'
ORDER BY pg_relation_size(indexrelid) DESC;
" 2>/dev/null | tee -a "$REPORT_FILE"

# ---------------------------------------------------------------------------
# 4. Sequential Scans vs Index Scans（表格級）
# ---------------------------------------------------------------------------
echo "" | tee -a "$REPORT_FILE"
echo "=== 4. Sequential Scan vs Index Scan ===" | tee -a "$REPORT_FILE"

$PSQL_CMD -c "
SELECT
    relname AS table,
    seq_scan,
    idx_scan,
    CASE WHEN seq_scan + idx_scan > 0
         THEN round(100.0 * idx_scan / (seq_scan + idx_scan), 2)
         ELSE 0 END AS idx_scan_pct,
    n_live_tup AS rows
FROM pg_stat_user_tables
WHERE n_live_tup > 100
ORDER BY seq_scan DESC;
" 2>/dev/null | tee -a "$REPORT_FILE"

# ---------------------------------------------------------------------------
# 5. EXPLAIN ANALYZE 常用查詢
# ---------------------------------------------------------------------------
echo "" | tee -a "$REPORT_FILE"
echo "=== 5. EXPLAIN ANALYZE 常用查詢 ===" | tee -a "$REPORT_FILE"

# 5a. 依 tenant_id 查 users
echo "--- 5a. User by tenant_id ---" | tee -a "$REPORT_FILE"
$PSQL_CMD -c "
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM users
WHERE tenant_id = (SELECT id FROM tenants LIMIT 1)
LIMIT 50;
" 2>/dev/null | tee -a "$REPORT_FILE"

# 5b. 依 tenant_id + created_at 查 audit_logs
echo "" | tee -a "$REPORT_FILE"
echo "--- 5b. AuditLog by tenant + date range ---" | tee -a "$REPORT_FILE"
$PSQL_CMD -c "
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM auditlogs
WHERE tenant_id = (SELECT id FROM tenants LIMIT 1)
  AND created_at >= NOW() - INTERVAL '30 days'
ORDER BY created_at DESC
LIMIT 20;
" 2>/dev/null | tee -a "$REPORT_FILE"

# 5c. 月度用量聚合
echo "" | tee -a "$REPORT_FILE"
echo "--- 5c. Monthly usage aggregation ---" | tee -a "$REPORT_FILE"
$PSQL_CMD -c "
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT
    tenant_id,
    SUM(input_tokens) + SUM(output_tokens) AS total_tokens,
    COUNT(*) AS query_count,
    SUM(estimated_cost_usd) AS total_cost
FROM usagerecords
WHERE created_at >= date_trunc('month', NOW())
GROUP BY tenant_id;
" 2>/dev/null | tee -a "$REPORT_FILE"

# 5d. 對話列表
echo "" | tee -a "$REPORT_FILE"
echo "--- 5d. User conversations ---" | tee -a "$REPORT_FILE"
$PSQL_CMD -c "
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM conversations
WHERE tenant_id = (SELECT id FROM tenants LIMIT 1)
  AND user_id = (SELECT id FROM users LIMIT 1)
ORDER BY updated_at DESC NULLS LAST
LIMIT 20;
" 2>/dev/null | tee -a "$REPORT_FILE"

# 5e. 文件列表
echo "" | tee -a "$REPORT_FILE"
echo "--- 5e. Documents by tenant + status ---" | tee -a "$REPORT_FILE"
$PSQL_CMD -c "
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM documents
WHERE tenant_id = (SELECT id FROM tenants LIMIT 1)
  AND status = 'processed'
ORDER BY created_at DESC
LIMIT 50;
" 2>/dev/null | tee -a "$REPORT_FILE"

# ---------------------------------------------------------------------------
# 6. 連線統計
# ---------------------------------------------------------------------------
echo "" | tee -a "$REPORT_FILE"
echo "=== 6. 連線統計 ===" | tee -a "$REPORT_FILE"

$PSQL_CMD -c "
SELECT
    state,
    COUNT(*) AS connections,
    MAX(EXTRACT(EPOCH FROM NOW() - state_change))::int AS max_idle_seconds
FROM pg_stat_activity
WHERE datname = '$DB_NAME'
GROUP BY state
ORDER BY connections DESC;
" 2>/dev/null | tee -a "$REPORT_FILE"

# ---------------------------------------------------------------------------
# 7. Cache Hit Ratio
# ---------------------------------------------------------------------------
echo "" | tee -a "$REPORT_FILE"
echo "=== 7. Buffer Cache Hit Ratio ===" | tee -a "$REPORT_FILE"

$PSQL_CMD -c "
SELECT
    sum(heap_blks_read) AS heap_read,
    sum(heap_blks_hit) AS heap_hit,
    CASE WHEN sum(heap_blks_hit) + sum(heap_blks_read) > 0
         THEN round(sum(heap_blks_hit)::numeric /
              (sum(heap_blks_hit) + sum(heap_blks_read)) * 100, 2)
         ELSE 100 END AS cache_hit_ratio_pct
FROM pg_statio_user_tables;
" 2>/dev/null | tee -a "$REPORT_FILE"

# ---------------------------------------------------------------------------
# 8. VACUUM 與 ANALYZE 狀態
# ---------------------------------------------------------------------------
echo "" | tee -a "$REPORT_FILE"
echo "=== 8. 最後 VACUUM / ANALYZE 時間 ===" | tee -a "$REPORT_FILE"

$PSQL_CMD -c "
SELECT
    relname AS table,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze,
    n_dead_tup AS dead_rows
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;
" 2>/dev/null | tee -a "$REPORT_FILE"

# ---------------------------------------------------------------------------
# 完成
# ---------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo "✅ 效能分析完成！報告已存至：${REPORT_FILE}"
echo "======================================================================"
