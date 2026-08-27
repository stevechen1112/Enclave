#!/usr/bin/env bash
# ========================================================
# Enclave Backup Entry
# ========================================================
# Canonical full backup (DB + uploads, credentials excluded):
#   ./scripts/backup.sh
#   → python scripts/ops_lifecycle.py backup
#
# CD / DB-only (pre-deploy, no uploads tar):
#   ./scripts/backup.sh --db-only
#   ./scripts/backup.sh --direct          # alias for --db-only via pg_dump
#
# Environment:
#   BACKUP_DIR, RETENTION_DAYS, DB_ADMIN_USER, DB_ADMIN_DATABASE, COMPOSE_SERVICE
# ========================================================

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
BACKUP_DB_USER="${DB_ADMIN_USER:-${POSTGRES_USER:-postgres}}"
BACKUP_DB_NAME="${DB_ADMIN_DATABASE:-${POSTGRES_DB:-enclave}}"
COMPOSE_SERVICE="${COMPOSE_SERVICE:-db}"
MODE="${1:-}"

# ── Full backup (canonical) ──
if [[ -z "${MODE}" ]] || [[ "${MODE}" == "--full" ]]; then
  echo "▸ Canonical full backup via ops_lifecycle.py"
  ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
  cd "${ROOT_DIR}"
  export BACKUP_DIR
  python scripts/ops_lifecycle.py backup
  exit $?
fi

if [[ "${MODE}" != "--db-only" ]] && [[ "${MODE}" != "--direct" ]]; then
  echo "Usage: $0 [--full|--db-only|--direct]"
  exit 2
fi

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/enclave_${TIMESTAMP}.sql.gz"
mkdir -p "${BACKUP_DIR}"

echo "════════════════════════════════════════════"
echo "  Enclave DB-only Backup — $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════"
echo "  Mode:      ${MODE}"
echo "  Database:  ${BACKUP_DB_NAME}"
echo "  Output:    ${BACKUP_FILE}"
echo "════════════════════════════════════════════"

echo ""
echo "▸ Creating database dump..."

if [[ "${MODE}" == "--direct" ]]; then
    pg_dump \
        -U "${BACKUP_DB_USER}" \
        -d "${BACKUP_DB_NAME}" \
        --format=plain \
        --no-owner \
        --no-privileges \
        --verbose \
        -f "${BACKUP_FILE%.gz}"
    gzip "${BACKUP_FILE%.gz}"
else
    # --db-only via compose
    docker compose exec -T "${COMPOSE_SERVICE}" \
        pg_dump \
        -U "${BACKUP_DB_USER}" \
        -d "${BACKUP_DB_NAME}" \
        --format=plain \
        --no-owner \
        --no-privileges \
        | gzip > "${BACKUP_FILE}"
fi

BACKUP_SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
echo "✓ Backup created: ${BACKUP_FILE} (${BACKUP_SIZE})"

echo ""
echo "▸ Verifying backup integrity..."
if gzip -t "${BACKUP_FILE}" 2>/dev/null; then
    echo "✓ Backup file integrity verified"
else
    echo "✗ Backup file is corrupted!"
    exit 1
fi

echo ""
echo "▸ Cleaning backups older than ${RETENTION_DAYS} days..."
DELETED_COUNT=$(find "${BACKUP_DIR}" -name "enclave_*.sql.gz" -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)
echo "✓ Deleted ${DELETED_COUNT} old backup(s)"

echo ""
echo "════════════════════════════════════════════"
echo "  ✓ DB-only backup complete!"
echo "════════════════════════════════════════════"
