#!/usr/bin/env python3
"""
Fix Celery Redis URL to include password and update admin email to valid domain.
"""
import paramiko
import time

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username="root", key_filename=KEY_FILE, timeout=30)

def run(cmd, timeout=30):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    rc = stdout.channel.recv_exit_status()
    return out, err, rc

def sql(stmt):
    escaped = stmt.replace("'", "'\"'\"'")
    cmd = f"docker exec aihr-db psql -U postgres -d aihr_prod -c '{escaped}'"
    return run(cmd)

print("=== 1. Ensure CELERY_* use REDIS_URL in compose ===")
run("cd /opt/aihr && sed -i 's|CELERY_BROKER_URL=.*|CELERY_BROKER_URL=${REDIS_URL}|' docker-compose.minimal.yml")
run("cd /opt/aihr && sed -i 's|CELERY_RESULT_BACKEND=.*|CELERY_RESULT_BACKEND=${REDIS_URL}|' docker-compose.minimal.yml")

out, _, _ = run("grep -n 'CELERY' /opt/aihr/docker-compose.minimal.yml")
print(out)

print("\n=== 2. Update .env superuser email ===")
run("cd /opt/aihr && sed -i 's|^FIRST_SUPERUSER_EMAIL=.*|FIRST_SUPERUSER_EMAIL=admin@example.com|' .env")
run("cd /opt/aihr && grep -n 'FIRST_SUPERUSER_EMAIL' .env")

print("\n=== 3. Update admin user email in DB ===")
_, err, rc = sql("UPDATE users SET email = 'admin@example.com' WHERE email = 'admin@aihr.local';")
print("OK" if rc == 0 else err[:120])

print("\n=== 4. Recreate web container ===")
run("cd /opt/aihr && docker compose -f docker-compose.minimal.yml up -d web", timeout=120)

time.sleep(20)
status, _, _ = run("docker ps --filter name=aihr-web --format '{{.Status}}'")
print(f"Web status: {status}")

print("\n=== 5. Verify web env ===")
out, _, _ = run("docker exec aihr-web env | grep -i 'celery\\|redis' | sort")
print(out)

ssh.close()
print("\nDone")
