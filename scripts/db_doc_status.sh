#!/usr/bin/env bash
set -euo pipefail

cd /opt/aihr

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d unihr_saas <<'SQL'
SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY status;
SQL
