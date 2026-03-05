#!/usr/bin/env bash
set -euo pipefail

cd /opt/aihr

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d postgres <<'SQL'
ALTER USER enclave WITH PASSWORD 'Elf3_T9nI0LYUBzWKZstiEv5WkF5rggfGM5-REO18lA';
SQL
