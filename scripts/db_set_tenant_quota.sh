#!/usr/bin/env bash
set -euo pipefail

cd /opt/aihr

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d enclave <<'SQL'
UPDATE tenants
SET max_documents = 1000,
    max_storage_mb = 10240,
    monthly_query_limit = 100000,
    monthly_token_limit = 10000000;
SQL
