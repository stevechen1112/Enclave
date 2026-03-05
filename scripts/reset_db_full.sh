#!/usr/bin/env bash
set -euo pipefail

cd /opt/aihr

PASS='Elf3_T9nI0LYUBzWKZstiEv5WkF5rggfGM5-REO18lA'

# Stop app services to release DB connections

docker compose -f docker-compose.prod.yml --env-file .env.production stop web worker

# Drop and recreate database

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d postgres <<'SQL'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'enclave'
  AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS enclave;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'enclave') THEN
    CREATE ROLE enclave WITH LOGIN PASSWORD 'TEMP_PASSWORD';
  END IF;
END
$$;
SQL

# Set correct password and create database

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d postgres -c "ALTER ROLE enclave WITH LOGIN PASSWORD '${PASS}';"

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d postgres -c "CREATE DATABASE enclave OWNER enclave;"

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE enclave TO enclave;"

# Enable pgvector

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db psql -U postgres -d enclave <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
SQL

# Start web service to run DB init scripts

docker compose -f docker-compose.prod.yml --env-file .env.production up -d web

# Create tables from models

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T web env PYTHONPATH=/code python /code/scripts/create_tables.py

# Seed initial data (superuser + demo tenant)

docker compose -f docker-compose.prod.yml --env-file .env.production exec -T web env PYTHONPATH=/code python /code/scripts/initial_data.py

# Restart app services

docker compose -f docker-compose.prod.yml --env-file .env.production up -d web worker
