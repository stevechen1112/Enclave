#!/usr/bin/env bash
# ========================================================
# Enclave Disaster Recovery Script
# ========================================================
# Full system recovery from a snapshot backup.
# Restores: Database → Redis → Uploads
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
docker compose stop web worker frontend 2>/dev/null || true
echo "✓ Services stopped"
echo ""

# ── Step 2: Restore Database ──
echo "━━━ [2/5] Restoring Database ━━━"
DB_DUMP=$(find "${SNAPSHOT_DIR}" -name "enclave_*.sql.gz" | head -1)
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

    # Restore
    gunzip -c "${DB_DUMP}" | \
        docker compose exec -T "${COMPOSE_SERVICE}" \
        psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -q

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
UPLOADS_ARCHIVE="${SNAPSHOT_DIR}/uploads.tar.gz"
if [[ -f "${UPLOADS_ARCHIVE}" ]]; then
    UPLOADS_DIR="./uploads"
    mkdir -p "${UPLOADS_DIR}"
    tar -xzf "${UPLOADS_ARCHIVE}" -C "${UPLOADS_DIR}"
    FILE_COUNT=$(find "${UPLOADS_DIR}" -type f | wc -l)
    echo "✓ Uploads restored (${FILE_COUNT} files)"
else
    echo "⚠ No uploads archive found, skipping"
fi
echo ""

# ── Step 5: Restart Everything ──
echo "━━━ [5/5] Starting Services ━━━"
docker compose start web worker frontend
echo "✓ All services started"

# ── Health Check ──
echo ""
echo "▸ Waiting for services to be healthy..."
sleep 5

HEALTH=$(curl -s http://localhost:8000/api/v1/admin/health 2>/dev/null || echo '{"status":"unknown"}')
echo "  Backend health: ${HEALTH}"

echo ""
echo "════════════════════════════════════════════"
echo "  ✓ Disaster recovery complete!"
echo "  Please verify system functionality manually."
echo "════════════════════════════════════════════"
