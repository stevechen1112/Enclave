#!/usr/bin/env bash
# Alembic migration dry-run — 不落地，只輸出將執行的 SQL 供審閱。
# 用法：
#   ./scripts/migration_dryrun.sh                 # 本機（web 容器或主機 venv）
#   ./scripts/migration_dryrun.sh --compose docker-compose.prod.yml --env .env.production
set -euo pipefail

COMPOSE_FILE=""
ENV_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --compose) COMPOSE_FILE="$2"; shift 2 ;;
    --env) ENV_FILE="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="artifacts/migration_dryrun_${STAMP}.sql"
mkdir -p artifacts

if [[ -n "$COMPOSE_FILE" ]]; then
  COMPOSE=(docker compose -f "$COMPOSE_FILE")
  [[ -n "$ENV_FILE" ]] && COMPOSE+=(--env-file "$ENV_FILE")
  echo "[dryrun] current revision:"
  "${COMPOSE[@]}" exec -T web alembic current
  echo "[dryrun] rendering SQL → ${OUT}"
  "${COMPOSE[@]}" exec -T web alembic upgrade head --sql > "$OUT"
else
  echo "[dryrun] current revision:"
  alembic current
  echo "[dryrun] rendering SQL → ${OUT}"
  alembic upgrade head --sql > "$OUT"
fi

LINES="$(wc -l < "$OUT")"
echo "[dryrun] done: ${OUT} (${LINES} lines) — 請人工審閱後再正式 upgrade"
