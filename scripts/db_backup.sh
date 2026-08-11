#!/usr/bin/env bash
# Enclave DB 備份（部署／migration 前必做）
# 用法：
#   本機開發：  ./scripts/db_backup.sh
#   Linode 主機：./scripts/db_backup.sh --compose docker-compose.prod.yml --env .env.production
# 產物：backups/enclave_<YYYYMMDD_HHMMSS>.sql.gz
set -euo pipefail

COMPOSE_FILE="docker-compose.yml"
ENV_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --compose) COMPOSE_FILE="$2"; shift 2 ;;
    --env) ENV_FILE="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

COMPOSE=(docker compose -f "$COMPOSE_FILE")
if [[ -n "$ENV_FILE" ]]; then
  COMPOSE+=(--env-file "$ENV_FILE")
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="backups"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/enclave_${STAMP}.sql.gz"

DB_SERVICE="db"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-enclave}"

echo "[backup] dumping ${DB_NAME} from service ${DB_SERVICE} → ${OUT}"
"${COMPOSE[@]}" exec -T "$DB_SERVICE" \
  pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-privileges \
  | gzip > "$OUT"

SIZE="$(du -h "$OUT" | cut -f1)"
echo "[backup] done: ${OUT} (${SIZE})"

# 保留最近 20 份，避免磁碟被備份塞滿
ls -1t "$OUT_DIR"/enclave_*.sql.gz 2>/dev/null | tail -n +21 | xargs -r rm -f
echo "[backup] retention: kept latest 20"
