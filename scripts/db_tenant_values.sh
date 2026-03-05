#!/usr/bin/env bash
set -euo pipefail

cd /opt/aihr

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d enclave <<'SQL'
SELECT id, name, plan, max_documents, max_storage_mb, monthly_query_limit, monthly_token_limit FROM tenants ORDER BY created_at DESC;
SQL
