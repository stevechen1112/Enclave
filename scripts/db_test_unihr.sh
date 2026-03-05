#!/usr/bin/env bash
set -euo pipefail

cd /opt/aihr

PASS='Elf3_T9nI0LYUBzWKZstiEv5WkF5rggfGM5-REO18lA'

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db bash -lc "PGPASSWORD='${PASS}' psql -U enclave -d enclave -c 'SELECT 1;'"
