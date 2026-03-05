#!/usr/bin/env bash
set -euo pipefail

cd /opt/aihr

PASS='Elf3_T9nI0LYUBzWKZstiEv5WkF5rggfGM5-REO18lA'

ROLE_EXISTS=$(docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='enclave';")
if [ -z "$ROLE_EXISTS" ]; then
  docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d postgres -c "CREATE ROLE enclave WITH LOGIN PASSWORD '${PASS}';"
fi

DB_EXISTS=$(docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='enclave';")
if [ -z "$DB_EXISTS" ]; then
  docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d postgres -c "CREATE DATABASE enclave OWNER enclave;"
fi

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE enclave TO enclave;"
