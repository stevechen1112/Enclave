#!/usr/bin/env python3
"""Add Celery worker service to docker-compose.minimal.yml and start it."""
import paramiko
import time

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

WORKER_BLOCK = """
  worker:
    build: .
    container_name: aihr-worker
    restart: unless-stopped
    command: celery -A app.celery_app worker --loglevel=info
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
    - APP_ENV=${APP_ENV:-production}
    - SECRET_KEY=${SECRET_KEY}
    - JWT_SECRET_KEY=${JWT_SECRET_KEY}
    - ACCESS_TOKEN_EXPIRE_MINUTES=${ACCESS_TOKEN_EXPIRE_MINUTES:-1440}
    - POSTGRES_SERVER=${POSTGRES_SERVER:-db}
    - POSTGRES_USER=${POSTGRES_USER:-postgres}
    - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
    - POSTGRES_DB=${POSTGRES_DB:-aihr_prod}
    - DATABASE_URL=${DATABASE_URL}
    - REDIS_HOST=${REDIS_HOST:-redis}
    - REDIS_PORT=${REDIS_PORT:-6379}
    - REDIS_PASSWORD=${REDIS_PASSWORD}
    - REDIS_URL=${REDIS_URL}
    - CELERY_BROKER_URL=${REDIS_URL}
    - CELERY_RESULT_BACKEND=${REDIS_URL}
    - BACKEND_CORS_ORIGINS=${BACKEND_CORS_ORIGINS}
    - FRONTEND_URL=${FRONTEND_URL}
    - VITE_API_URL=${VITE_API_URL}
    - OPENAI_API_KEY=${OPENAI_API_KEY}
    - OPENAI_MODEL=${OPENAI_MODEL:-gpt-4o-mini}
    - OPENAI_TEMPERATURE=${OPENAI_TEMPERATURE:-0.3}
    - OPENAI_MAX_TOKENS=${OPENAI_MAX_TOKENS:-1500}
    - VOYAGE_API_KEY=${VOYAGE_API_KEY}
    - VOYAGE_MODEL=${VOYAGE_MODEL:-voyage-4-lite}
    - EMBEDDING_DIMENSION=${EMBEDDING_DIMENSION:-1024}
    - LLAMAPARSE_API_KEY=${LLAMAPARSE_API_KEY}
    - LLAMAPARSE_ENABLED=${LLAMAPARSE_ENABLED:-true}
    - CORE_API_URL=${CORE_API_URL}
    - CORE_SERVICE_TOKEN=${CORE_SERVICE_TOKEN}
    volumes:
    - uploads_data:/code/uploads
"""

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username="root", key_filename=KEY_FILE, timeout=30)

def run(cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    rc = stdout.channel.recv_exit_status()
    return out, err, rc

print("=== 1. Read compose ===")
raw, err, rc = run("cat /opt/aihr/docker-compose.minimal.yml")
if rc != 0:
    print(err)
    raise SystemExit(1)

if "\n  worker:" in raw:
    print("Worker service already exists")
else:
    if "\n  frontend:" in raw:
        updated = raw.replace("\n  frontend:", f"\n{WORKER_BLOCK}\n  frontend:")
    else:
        updated = raw + "\n" + WORKER_BLOCK
    # Write back
    cmd = "cat > /opt/aihr/docker-compose.minimal.yml <<'EOF'\n" + updated + "\nEOF\n"
    run(cmd, timeout=30)
    print("Worker service added")

print("\n=== 2. Start worker ===")
run("cd /opt/aihr && docker compose -f docker-compose.minimal.yml up -d worker", timeout=120)

time.sleep(10)
status, _, _ = run("docker ps --filter name=aihr-worker --format '{{.Status}}'")
print(f"Worker status: {status}")

ssh.close()
