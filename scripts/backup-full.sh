#!/usr/bin/env bash
# ========================================================
# Enclave Full System Backup (DB + Redis + Uploads)
# ========================================================
# Creates a complete system backup including:
#   1. PostgreSQL database dump
#   2. Redis RDB snapshot
#   3. Uploaded files (if any)
#
# Usage:
#   chmod +x scripts/backup-full.sh
#   ./scripts/backup-full.sh
#
# Environment:
#   BACKUP_DIR       — Base backup directory (default: ./backups)
#   RETENTION_DAYS   — Days to keep backups (default: 30)
# ========================================================

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
SNAPSHOT_DIR="${BACKUP_DIR}/snapshot_${TIMESTAMP}"

echo "════════════════════════════════════════════"
echo "  Enclave Full System Backup"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════"

mkdir -p "${SNAPSHOT_DIR}"

# ── 1. Database ──
echo ""
echo "━━━ [1/3] PostgreSQL Database ━━━"
BACKUP_DIR="${SNAPSHOT_DIR}" bash scripts/backup.sh

# Move the dump into the snapshot folder (already there via BACKUP_DIR)

# ── 2. Redis ──
echo ""
echo "━━━ [2/3] Redis Snapshot ━━━"

# Trigger Redis BGSAVE
echo "▸ Triggering Redis BGSAVE..."
docker compose exec -T redis redis-cli BGSAVE 2>/dev/null || true
sleep 2

# Copy RDB file
if docker compose exec -T redis test -f /data/dump.rdb 2>/dev/null; then
    docker compose cp redis:/data/dump.rdb "${SNAPSHOT_DIR}/redis_dump.rdb"
    REDIS_SIZE=$(du -sh "${SNAPSHOT_DIR}/redis_dump.rdb" | cut -f1)
    echo "✓ Redis snapshot saved (${REDIS_SIZE})"
else
    echo "⚠ Redis dump.rdb not found (cache-only mode, skipping)"
fi

# ── 3. Uploads ──
echo ""
echo "━━━ [3/3] Uploaded Files ━━━"

UPLOADS_DIR="./uploads"
if [[ -d "${UPLOADS_DIR}" ]] && [[ -n "$(ls -A ${UPLOADS_DIR} 2>/dev/null)" ]]; then
    tar -czf "${SNAPSHOT_DIR}/uploads.tar.gz" -C "${UPLOADS_DIR}" .
    UPLOADS_SIZE=$(du -sh "${SNAPSHOT_DIR}/uploads.tar.gz" | cut -f1)
    echo "✓ Uploads archived (${UPLOADS_SIZE})"
else
    echo "⚠ No uploads directory or empty, skipping"
fi

# ── Summary ──
echo ""
echo "━━━ Snapshot Contents ━━━"
ls -lh "${SNAPSHOT_DIR}"/
TOTAL_SIZE=$(du -sh "${SNAPSHOT_DIR}" | cut -f1)

# ── Clean old snapshots ──
echo ""
echo "▸ Cleaning snapshots older than ${RETENTION_DAYS} days..."
DELETED_COUNT=$(find "${BACKUP_DIR}" -maxdepth 1 -name "snapshot_*" -type d -mtime "+${RETENTION_DAYS}" -print -exec rm -rf {} \; | wc -l)
echo "✓ Deleted ${DELETED_COUNT} old snapshot(s)"

echo ""
echo "════════════════════════════════════════════"
echo "  ✓ Full backup complete!"
echo "  Location: ${SNAPSHOT_DIR}"
echo "  Total:    ${TOTAL_SIZE}"
echo "════════════════════════════════════════════"
