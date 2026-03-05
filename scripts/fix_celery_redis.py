#!/usr/bin/env python3
"""
Fix remaining issues:
1. Celery Redis URL in web container
2. metadata_json column type (json → jsonb)
3. Check .env in container for CELERY vars
4. Check email validation error details
"""
import paramiko
import time
import requests

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

# ═════════════════════════════════
# 1. Check current docker-compose.minimal.yml
# ═════════════════════════════════
print("=== 1. Current docker-compose.minimal.yml ===")
out, _, _ = run("cat /opt/aihr/docker-compose.minimal.yml")
print(out)

# ═════════════════════════════════
# 2. Check .env in container for Celery vars
# ═════════════════════════════════
print("\n=== 2. Celery env vars inside web container ===")
out, _, _ = run("docker exec aihr-web env | grep -i celery")
print(out if out else "(NO CELERY env vars)")
out, _, _ = run("docker exec aihr-web env | grep -i redis")
print(out if out else "(NO REDIS env vars)")

# ═════════════════════════════════
# 3. Check .env file content for celery
# ═════════════════════════════════
print("\n=== 3. .env file celery/redis vars ===")
out, _, _ = run("grep -i 'celery\\|redis' /opt/aihr/.env")
print(out)

# ═════════════════════════════════
# 4. Fix metadata_json to jsonb
# ═════════════════════════════════
print("\n=== 4. Fix metadata_json column type ===")
out, err, rc = sql("ALTER TABLE documentchunks ALTER COLUMN metadata_json TYPE jsonb USING metadata_json::jsonb")
print(f"  Result: {'OK' if rc == 0 else err[:100]}")

# ═════════════════════════════════
# 5. Add CELERY vars to docker-compose.minimal.yml
# ═════════════════════════════════
print("\n=== 5. Fix docker-compose.minimal.yml ===")

# Read current file
out, _, _ = run("cat /opt/aihr/docker-compose.minimal.yml")

# Check if CELERY_BROKER_URL is already in the file
if "CELERY_BROKER_URL" not in out:
    # Add CELERY env vars to web service
    # We need to add them under the web service's environment section
    # Using sed to add after REDIS_HOST line
    run("""cd /opt/aihr && sed -i '/REDIS_HOST=redis/a\\      - CELERY_BROKER_URL=redis://redis:6379/0\\n      - CELERY_RESULT_BACKEND=redis://redis:6379/0' docker-compose.minimal.yml""")
    print("  Added CELERY_BROKER_URL and CELERY_RESULT_BACKEND to web service")
else:
    print("  CELERY vars already present")

# Verify
out, _, _ = run("cat /opt/aihr/docker-compose.minimal.yml")
print(out)

# ═════════════════════════════════
# 6. Restart web service
# ═════════════════════════════════
print("\n=== 6. Restarting web service ===")
out, err, _ = run("cd /opt/aihr && docker compose -f docker-compose.minimal.yml restart web", timeout=60)
print(out, err)
time.sleep(15)

out, _, _ = run("docker ps --filter name=aihr-web --format '{{.Status}}'")
print(f"  Web status: {out}")

# ═════════════════════════════════
# 7. Test upload and check for errors
# ═════════════════════════════════
print("\n=== 7. Quick test after fix ===")
try:
    r = requests.post("http://api.172-237-5-254.sslip.io/api/v1/auth/login/access-token",
                       data={"username": "admin@aihr.local", "password": "mcWzOEha0w7zKH9u53yG7Q"}, timeout=15)
    token = r.json().get("access_token")
    print(f"  Login: {r.status_code}")
    
    # Test upload
    r2 = requests.post("http://api.172-237-5-254.sslip.io/api/v1/documents/upload",
                        headers={"Authorization": f"Bearer {token}"},
                        files={"file": ("test.txt", b"This is a test document about HR policies. Employees get 14 days of annual leave.", "text/plain")},
                        timeout=30)
    print(f"  Upload: {r2.status_code} - {r2.text[:200]}")
    
    # Test /users/me
    r3 = requests.get("http://api.172-237-5-254.sslip.io/api/v1/users/me",
                       headers={"Authorization": f"Bearer {token}"}, timeout=10)
    print(f"  Users/me: {r3.status_code} - {r3.text[:200]}")
    
    # Test create user with detailed error
    r4 = requests.post("http://api.172-237-5-254.sslip.io/api/v1/users/",
                        headers={"Authorization": f"Bearer {token}"},
                        json={
                            "email": "test-user@aihr.local",
                            "password": "TestPass123!",
                            "full_name": "Test User",
                            "role": "employee",
                            "tenant_id": "b4539d8d-ea56-460f-bf68-9b1fececced8"
                        }, timeout=10)
    print(f"  Create User: {r4.status_code} - {r4.text[:300]}")
    
except Exception as e:
    print(f"  Error: {e}")

# ═════════════════════════════════
# 8. Check fresh errors
# ═════════════════════════════════
time.sleep(3)
print("\n=== 8. Fresh web errors ===")
out, _, _ = run("docker logs aihr-web --since 30s 2>&1 | grep -i 'error\\|traceback\\|exception\\|fail' | head -20")
print(out if out else "(no errors)")

ssh.close()
print("\nDone!")
