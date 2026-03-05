#!/usr/bin/env python3
"""
Fix Celery Redis connection + recreate web container
Root cause: CELERY_BROKER_URL not set in web container env → defaults to redis://localhost:6379/0
Also checks if Redis needs password and if worker service exists
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

# ═════════════════════════════════
# 1. Check if Redis actually requires password
# ═════════════════════════════════
print("=== 1. Check Redis auth status ===")
out, _, _ = run("docker exec aihr-redis redis-cli ping")
print(f"  Redis PING (no auth): {out}")
out, _, _ = run("docker exec aihr-redis env | grep REDIS_PASSWORD")
print(f"  Redis container REDIS_PASSWORD env: {out or '(not set → no auth)'}")

# ═════════════════════════════════
# 2. Fix docker-compose.minimal.yml - write clean version
# ═════════════════════════════════
print("\n=== 2. Write fixed docker-compose.minimal.yml ===")

# Read current file to preserve structure, then add missing vars
out, _, _ = run("cat /opt/aihr/docker-compose.minimal.yml")

# Check if CELERY_BROKER_URL already there from previous sed
if "CELERY_BROKER_URL" in out:
    print("  CELERY vars already in file, checking format...")
    # Show the celery lines
    out2, _, _ = run("grep CELERY /opt/aihr/docker-compose.minimal.yml")
    print(f"  Current: {out2}")
    # Fix if needed - replace with correct values using REDIS_URL (which includes password IF needed)
    run("cd /opt/aihr && sed -i 's|CELERY_BROKER_URL=.*|CELERY_BROKER_URL=redis://redis:6379/0|' docker-compose.minimal.yml")
    run("cd /opt/aihr && sed -i 's|CELERY_RESULT_BACKEND=.*|CELERY_RESULT_BACKEND=redis://redis:6379/0|' docker-compose.minimal.yml")
else:
    # Add CELERY vars after REDIS_URL line
    run("""cd /opt/aihr && sed -i '/REDIS_URL=/a\\    - CELERY_BROKER_URL=redis://redis:6379/0\\n    - CELERY_RESULT_BACKEND=redis://redis:6379/0' docker-compose.minimal.yml""")

# Verify
out, _, _ = run("grep -n 'CELERY\|REDIS' /opt/aihr/docker-compose.minimal.yml")
print(f"  Updated:\n{out}")

# ═════════════════════════════════
# 3. Recreate web container (up -d, NOT restart!)
# ═════════════════════════════════
print("\n=== 3. Recreate web container ===")
out, err, _ = run("cd /opt/aihr && docker compose -f docker-compose.minimal.yml up -d web", timeout=120)
print(out)
print(err[:200] if err else "")

time.sleep(20)  # Wait for health check
out, _, _ = run("docker ps --filter name=aihr-web --format '{{.Status}}'")
print(f"  Web status: {out}")

# ═════════════════════════════════
# 4. Verify env vars in new container
# ═════════════════════════════════
print("\n=== 4. Verify env vars ===")
out, _, _ = run("docker exec aihr-web env | grep -i 'celery\\|redis'")
print(out)

# ═════════════════════════════════
# 5. Test upload + users/me
# ═════════════════════════════════
print("\n=== 5. Quick tests ===")
try:
    r = requests.post(
        "http://api.172-237-5-254.sslip.io/api/v1/auth/login/access-token",
        data={"username": "admin@example.com", "password": "mcWzOEha0w7zKH9u53yG7Q"},
        timeout=15
    )
    token = r.json().get("access_token")
    print(f"  Login: {r.status_code}")

    # /users/me
    r2 = requests.get(
        "http://api.172-237-5-254.sslip.io/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    print(f"  Users/me: {r2.status_code} → {r2.text[:300]}")

    # Upload test file
    r3 = requests.post(
        "http://api.172-237-5-254.sslip.io/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("test.txt", b"Test document HR policies\nEmployees get 14 days annual leave.", "text/plain")},
        timeout=30
    )
    print(f"  Upload: {r3.status_code} → {r3.text[:300]}")

    # Create user with valid email domain
    r4 = requests.post(
        "http://api.172-237-5-254.sslip.io/api/v1/users/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "test-user@example.com",
            "password": "TestPass123!",
            "full_name": "Test User",
            "role": "employee",
            "tenant_id": "b4539d8d-ea56-460f-bf68-9b1fececced8"
        },
        timeout=10
    )
    print(f"  Create user: {r4.status_code} → {r4.text[:300]}")

    # Test chat
    r5 = requests.post(
        "http://api.172-237-5-254.sslip.io/api/v1/chat/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "你好"},
        timeout=60
    )
    print(f"  Chat: {r5.status_code} → {r5.text[:300]}")

except Exception as e:
    print(f"  Error: {e}")

# ═════════════════════════════════
# 6. Fresh errors
# ═════════════════════════════════
time.sleep(3)
print("\n=== 6. Fresh web errors ===")
out, _, _ = run("docker logs aihr-web --since 60s 2>&1 | grep -i 'error\\|exception\\|traceback' | head -20")
print(out if out else "(no errors)")

ssh.close()
print("\nDone!")
