#!/usr/bin/env bash
# ========================================================
# Enclave Disaster Recovery Script
# ========================================================
# Full system recovery from a snapshot backup.
# Restores: Database → Redis → canonical upload volume
#
# Usage:
#   ./scripts/disaster-recovery.sh backups/snapshot_20240101_020000
#
# ⚠️ This will REPLACE all current data!
# ========================================================

set -euo pipefail

SNAPSHOT_DIR="${1:-}"

if [[ -z "${SNAPSHOT_DIR}" ]]; then
    echo "Usage: $0 <snapshot_directory>"
    echo ""
    echo "Available snapshots:"
    ls -d backups/snapshot_* 2>/dev/null || echo "  (none found)"
    exit 1
fi

if [[ ! -d "${SNAPSHOT_DIR}" ]]; then
    echo "✗ Snapshot directory not found: ${SNAPSHOT_DIR}"
    exit 1
fi

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-enclave}"
COMPOSE_SERVICE="${COMPOSE_SERVICE:-db}"

echo "════════════════════════════════════════════"
echo "  Enclave Disaster Recovery"
echo "════════════════════════════════════════════"
echo "  Snapshot: ${SNAPSHOT_DIR}"
echo ""
echo "  Contents:"
ls -lh "${SNAPSHOT_DIR}"/
echo ""
echo "  ⚠️  WARNING: This will REPLACE all current data!"
echo ""

read -p "  Type 'RESTORE' to confirm: " CONFIRM
if [[ "${CONFIRM}" != "RESTORE" ]]; then
    echo "  Recovery cancelled."
    exit 0
fi

echo ""

# ── Step 1: Stop application ──
echo "━━━ [1/5] Stopping Services ━━━"
docker compose stop gateway frontend web worker worker-beat 2>/dev/null || true
echo "✓ Services stopped"
echo ""

# ── Step 2: Restore Database ──
echo "━━━ [2/5] Restoring Database ━━━"
DB_DUMP=$(find "${SNAPSHOT_DIR}" -maxdepth 1 -type f \( -name "enclave_*.sql" -o -name "enclave_*.sql.gz" \) | head -1)
if [[ -n "${DB_DUMP}" ]]; then
    echo "▸ Using backup: ${DB_DUMP}"

    # Terminate connections
    docker compose exec -T "${COMPOSE_SERVICE}" \
        psql -U "${POSTGRES_USER}" -c "
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = '${POSTGRES_DB}' AND pid <> pg_backend_pid();
        " 2>/dev/null || true

    # Drop and recreate
    docker compose exec -T "${COMPOSE_SERVICE}" \
        dropdb -U "${POSTGRES_USER}" --if-exists "${POSTGRES_DB}"
    docker compose exec -T "${COMPOSE_SERVICE}" \
        createdb -U "${POSTGRES_USER}" "${POSTGRES_DB}"

    # Restore the exact format emitted by ops_lifecycle.py backup. Legacy
    # compressed snapshots remain readable for backward compatibility.
    if [[ "${DB_DUMP}" == *.gz ]]; then
        gunzip -c "${DB_DUMP}" | \
            docker compose exec -T "${COMPOSE_SERVICE}" \
            psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -q
    else
        docker compose exec -T "${COMPOSE_SERVICE}" \
            psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -q \
            < "${DB_DUMP}"
    fi

    TABLE_COUNT=$(docker compose exec -T "${COMPOSE_SERVICE}" \
        psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -c \
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")
    echo "✓ Database restored (${TABLE_COUNT} tables)"
else
    echo "⚠ No database dump found in snapshot, skipping"
fi
echo ""

# ── Step 3: Restore Redis ──
echo "━━━ [3/5] Restoring Redis ━━━"
REDIS_DUMP="${SNAPSHOT_DIR}/redis_dump.rdb"
if [[ -f "${REDIS_DUMP}" ]]; then
    docker compose stop redis
    docker compose cp "${REDIS_DUMP}" redis:/data/dump.rdb
    docker compose start redis
    sleep 2
    echo "✓ Redis data restored"
else
    echo "⚠ No Redis dump found, skipping (cache will rebuild)"
fi
echo ""

# ── Step 4: Restore Uploads ──
echo "━━━ [4/5] Restoring Uploads ━━━"
UPLOADS_ARCHIVE=$(find "${SNAPSHOT_DIR}" -maxdepth 1 -type f \( -name "uploads_*.tgz" -o -name "uploads.tar.gz" \) | head -1)
if [[ -f "${UPLOADS_ARCHIVE}" ]]; then
    # Production stores uploads in a named volume, not the host ./uploads path.
    # init-storage is a narrow one-shot service with only that volume mounted.
    docker compose run --rm -T --no-deps --entrypoint sh init-storage -c \
        'test "$(readlink -f /code/uploads)" = "/code/uploads" && find /code/uploads -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar -xzf - -C /code' \
        < "${UPLOADS_ARCHIVE}"
    FILE_COUNT=$(docker compose run --rm -T --no-deps --entrypoint sh init-storage -c \
        'find /code/uploads -type f | wc -l')
    echo "✓ Canonical upload volume restored (${FILE_COUNT} files)"
else
    echo "⚠ No uploads archive found, skipping"
fi
echo ""

# ── Step 5: Restart Everything ──
echo "━━━ [5/5] Starting Services ━━━"
docker compose start web worker worker-beat frontend gateway
echo "✓ All services started"

# ── Health Check ──
echo ""
echo "▸ Waiting for services to be healthy..."
sleep 5

HEALTH_URL="${HEALTH_URL:-http://localhost/health}"
HEALTH=$(curl -fsS "${HEALTH_URL}" 2>/dev/null || echo '{"status":"unknown"}')
echo "  Backend health: ${HEALTH}"

echo ""
echo "════════════════════════════════════════════"
echo "  ✓ Disaster recovery complete!"
echo "  Run sealed retrieval, tenant-isolation, asset-read, and review smoke gates now."
echo "════════════════════════════════════════════"
