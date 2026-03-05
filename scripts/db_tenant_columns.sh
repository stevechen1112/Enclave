#!/usr/bin/env bash
set -euo pipefail

cd /opt/aihr

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d unihr_saas <<'SQL'
SELECT column_name FROM information_schema.columns WHERE table_name='tenants' ORDER BY ordinal_position;
SQL
