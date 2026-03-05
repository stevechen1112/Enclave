#!/usr/bin/env bash
# ========================================================
# Enclave Database Restore Script
# ========================================================
# Restores a PostgreSQL dump from a backup file.
# Supports both Docker and direct psql restore.
#
# Usage:
#   chmod +x scripts/restore.sh
#   ./scripts/restore.sh backups/enclave_20240101_020000.sql.gz
#   ./scripts/restore.sh --direct backups/enclave_20240101_020000.sql.gz
#
# ⚠️ WARNING: This will DROP and RECREATE the database!
# ========================================================

set -euo pipefail

# ── Parse arguments ──
MODE="docker"
BACKUP_FILE=""

for arg in "$@"; do
    case "${arg}" in
        --direct) MODE="direct" ;;
        *)        BACKUP_FILE="${arg}" ;;
    esac
done

if [[ -z "${BACKUP_FILE}" ]]; then
    echo "Usage: $0 [--direct] <backup_file.sql.gz>"
    echo ""
    echo "Available backups:"
    ls -lh backups/enclave_*.sql.gz 2>/dev/null || echo "  (none found)"
    exit 1
fi

if [[ ! -f "${BACKUP_FILE}" ]]; then
    echo "✗ Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

# ── Configuration ──
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-enclave}"
COMPOSE_SERVICE="${COMPOSE_SERVICE:-db}"

echo "════════════════════════════════════════════"
echo "  Enclave Database Restore"
echo "════════════════════════════════════════════"
echo "  Mode:      ${MODE}"
echo "  Database:  ${POSTGRES_DB}"
echo "  Backup:    ${BACKUP_FILE}"
echo "════════════════════════════════════════════"
echo ""
echo "  ⚠️  WARNING: This will DROP and RECREATE the database!"
echo "  ⚠️  All current data will be LOST!"
echo ""

# ── Confirmation ──
read -p "  Are you sure? (type 'yes' to confirm): " CONFIRM
if [[ "${CONFIRM}" != "yes" ]]; then
    echo ""
    echo "  Restore cancelled."
    exit 0
fi

# ── Step 1: Verify backup ──
echo ""
echo "▸ Verifying backup integrity..."
if gzip -t "${BACKUP_FILE}" 2>/dev/null; then
    echo "✓ Backup file integrity verified"
else
    echo "✗ Backup file is corrupted!"
    exit 1
fi

# ── Step 2: Stop application ──
echo ""
echo "▸ Stopping application services..."
if [[ "${MODE}" == "docker" ]]; then
    docker compose stop web worker 2>/dev/null || true
    echo "✓ Application services stopped"
fi

# ── Step 3: Restore database ──
echo ""
echo "▸ Restoring database..."

if [[ "${MODE}" == "--direct" ]] || [[ "${MODE}" == "direct" ]]; then
    # Direct restore
    dropdb -U "${POSTGRES_USER}" --if-exists "${POSTGRES_DB}"
    createdb -U "${POSTGRES_USER}" "${POSTGRES_DB}"
    gunzip -c "${BACKUP_FILE}" | psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -q
else
    # Docker restore
    docker compose exec -T "${COMPOSE_SERVICE}" \
        psql -U "${POSTGRES_USER}" -c "
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = '${POSTGRES_DB}' AND pid <> pg_backend_pid();
        " 2>/dev/null || true

    docker compose exec -T "${COMPOSE_SERVICE}" \
        dropdb -U "${POSTGRES_USER}" --if-exists "${POSTGRES_DB}"

    docker compose exec -T "${COMPOSE_SERVICE}" \
        createdb -U "${POSTGRES_USER}" "${POSTGRES_DB}"

    gunzip -c "${BACKUP_FILE}" | \
        docker compose exec -T "${COMPOSE_SERVICE}" \
        psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -q
fi

echo "✓ Database restored successfully"

# ── Step 4: Restart application ──
echo ""
echo "▸ Restarting application services..."
if [[ "${MODE}" == "docker" ]]; then
    docker compose start web worker
    echo "✓ Application services restarted"
fi

# ── Step 5: Verify ──
echo ""
echo "▸ Verifying restore..."
if [[ "${MODE}" == "docker" ]]; then
    TABLE_COUNT=$(docker compose exec -T "${COMPOSE_SERVICE}" \
        psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -c \
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")
else
    TABLE_COUNT=$(psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -c \
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")
fi

echo "✓ Tables restored: ${TABLE_COUNT}"

echo ""
echo "════════════════════════════════════════════"
echo "  ✓ Restore complete!"
echo "════════════════════════════════════════════"
