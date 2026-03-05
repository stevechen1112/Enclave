#!/usr/bin/env bash
# ========================================================
# Enclave Database Backup Script
# ========================================================
# Creates a compressed PostgreSQL dump with timestamp.
# Supports both Docker and direct pg_dump.
# Manages retention (default: 30 days).
#
# Usage:
#   chmod +x scripts/backup.sh
#   ./scripts/backup.sh                     # Docker mode
#   ./scripts/backup.sh --direct            # Direct pg_dump
#
# Environment variables:
#   BACKUP_DIR       — Backup directory (default: ./backups)
#   RETENTION_DAYS   — Days to keep backups (default: 30)
#   POSTGRES_USER    — DB user (default: postgres)
#   POSTGRES_DB      — DB name (default: enclave)
#   COMPOSE_SERVICE  — Docker compose DB service (default: db)
#
# Cron example (daily at 2 AM):
#   0 2 * * * cd /path/to/aihr && ./scripts/backup.sh >> /var/log/enclave-backup.log 2>&1
# ========================================================

set -euo pipefail

# ── Configuration ──
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-enclave}"
COMPOSE_SERVICE="${COMPOSE_SERVICE:-db}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/enclave_${TIMESTAMP}.sql.gz"
MODE="${1:-docker}"

# ── Ensure backup directory exists ──
mkdir -p "${BACKUP_DIR}"

echo "════════════════════════════════════════════"
echo "  Enclave Backup — $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════"
echo "  Mode:      ${MODE}"
echo "  Database:  ${POSTGRES_DB}"
echo "  Output:    ${BACKUP_FILE}"
echo "════════════════════════════════════════════"

# ── Step 1: Create backup ──
echo ""
echo "▸ Creating database dump..."

if [[ "${MODE}" == "--direct" ]]; then
    # Direct pg_dump (non-Docker) — plain SQL to match restore
    pg_dump \
        -U "${POSTGRES_USER}" \
        -d "${POSTGRES_DB}" \
        --format=plain \
        --no-owner \
        --no-privileges \
        --verbose \
        -f "${BACKUP_FILE%.gz}"

    gzip "${BACKUP_FILE%.gz}"
else
    # Docker mode
    docker compose exec -T "${COMPOSE_SERVICE}" \
        pg_dump \
        -U "${POSTGRES_USER}" \
        -d "${POSTGRES_DB}" \
        --format=plain \
        --no-owner \
        --no-privileges \
        | gzip > "${BACKUP_FILE}"
fi

# ── Verify backup ──
BACKUP_SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
echo "✓ Backup created: ${BACKUP_FILE} (${BACKUP_SIZE})"

# ── Step 2: Verify integrity ──
echo ""
echo "▸ Verifying backup integrity..."
if gzip -t "${BACKUP_FILE}" 2>/dev/null; then
    echo "✓ Backup file integrity verified"
else
    echo "✗ Backup file is corrupted!"
    exit 1
fi

# ── Step 3: Clean old backups ──
echo ""
echo "▸ Cleaning backups older than ${RETENTION_DAYS} days..."
DELETED_COUNT=$(find "${BACKUP_DIR}" -name "enclave_*.sql.gz" -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)
echo "✓ Deleted ${DELETED_COUNT} old backup(s)"

# ── Step 4: List remaining backups ──
echo ""
echo "▸ Current backups:"
ls -lh "${BACKUP_DIR}"/enclave_*.sql.gz 2>/dev/null || echo "  (none)"

TOTAL_COUNT=$(find "${BACKUP_DIR}" -name "enclave_*.sql.gz" | wc -l)
TOTAL_SIZE=$(du -sh "${BACKUP_DIR}" | cut -f1)
echo ""
echo "  Total: ${TOTAL_COUNT} backup(s), ${TOTAL_SIZE}"

echo ""
echo "════════════════════════════════════════════"
echo "  ✓ Backup complete!"
echo "════════════════════════════════════════════"
