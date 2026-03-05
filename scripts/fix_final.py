#!/usr/bin/env python3
"""
Final fixes:
1. CELERY_BROKER_URL with Redis password
2. Change superuser email from @aihr.local to @example.com 
3. Recreate web container
"""
import paramiko
import time
import requests

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"
REDIS_PW = "5VNPMA19neEIc1NSpeNLSvRU5FxfCpvKzPGgZs1_NO0"
REDIS_URL = f"redis://:{REDIS_PW}@redis:6379/0"

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

# ═══════════════════════════════════
# 1. Fix CELERY URLs with password
# ═══════════════════════════════════
print("=== 1. Fix CELERY URLs with Redis password ===")
# Update in docker-compose.minimal.yml
run(f"""cd /opt/aihr && sed -i 's|CELERY_BROKER_URL=.*|CELERY_BROKER_URL={REDIS_URL}|' docker-compose.minimal.yml""")
run(f"""cd /opt/aihr && sed -i 's|CELERY_RESULT_BACKEND=.*|CELERY_RESULT_BACKEND={REDIS_URL}|' docker-compose.minimal.yml""")

# Also update .env
run(f"""cd /opt/aihr && sed -i 's|^CELERY_BROKER_URL=.*|CELERY_BROKER_URL={REDIS_URL}|' .env""")
run(f"""cd /opt/aihr && sed -i 's|^CELERY_RESULT_BACKEND=.*|CELERY_RESULT_BACKEND={REDIS_URL}|' .env""")

out, _, _ = run("grep CELERY /opt/aihr/docker-compose.minimal.yml")
print(f"  compose: {out}")

# ═══════════════════════════════════
# 2. Change superuser email
# ═══════════════════════════════════
print("\n=== 2. Change superuser email ===")
out, err, rc = sql("UPDATE users SET email = 'admin@example.com' WHERE email = 'admin@aihr.local'")
print(f"  Result: {out} (rc={rc})")

# Also update .env FIRST_SUPERUSER_EMAIL
run("cd /opt/aihr && sed -i 's|FIRST_SUPERUSER_EMAIL=.*|FIRST_SUPERUSER_EMAIL=admin@example.com|' .env")

# ═══════════════════════════════════
# 3. Recreate web container
# ═══════════════════════════════════
print("\n=== 3. Recreate web container ===")
out, err, _ = run("cd /opt/aihr && docker compose -f docker-compose.minimal.yml up -d web", timeout=120)
print(f"  {err[:200] if err else out[:200]}")

time.sleep(20)
out, _, _ = run("docker ps --filter name=aihr-web --format '{{.Status}}'")
print(f"  Web status: {out}")

# ═══════════════════════════════════
# 4. Verify CELERY env in container
# ═══════════════════════════════════
print("\n=== 4. Verify env vars ===")
out, _, _ = run("docker exec aihr-web env | grep CELERY")
print(f"  {out}")

# ═══════════════════════════════════
# 5. Test all key endpoints
# ═══════════════════════════════════
print("\n=== 5. Test endpoints ===")
try:
    # Login with new email
    r = requests.post(
        "http://api.172-237-5-254.sslip.io/api/v1/auth/login/access-token",
        data={"username": "admin@example.com", "password": "mcWzOEha0w7zKH9u53yG7Q"},
        timeout=15
    )
    print(f"  Login: {r.status_code}")
    if r.status_code != 200:
        print(f"    Response: {r.text[:200]}")
        # If login fails, the password hash might need regeneration
        # Let's try the old email
        r = requests.post(
            "http://api.172-237-5-254.sslip.io/api/v1/auth/login/access-token",
            data={"username": "admin@aihr.local", "password": "mcWzOEha0w7zKH9u53yG7Q"},
            timeout=15
        )
        print(f"  Login (old email): {r.status_code}")
    
    token = r.json().get("access_token")
    if not token:
        print(f"  NO TOKEN! Response: {r.text[:200]}")
        raise SystemExit(1)

    # /users/me
    r2 = requests.get(
        "http://api.172-237-5-254.sslip.io/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    print(f"  Users/me: {r2.status_code} → {r2.text[:200]}")

    # Upload
    r3 = requests.post(
        "http://api.172-237-5-254.sslip.io/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("test.txt", b"HR policy test content. Employees get 14 days annual leave.", "text/plain")},
        timeout=30
    )
    print(f"  Upload: {r3.status_code} → {r3.text[:200]}")

    # Chat with correct field name
    r4 = requests.post(
        "http://api.172-237-5-254.sslip.io/api/v1/chat/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "你好"},
        timeout=60
    )
    print(f"  Chat: {r4.status_code} → {r4.text[:200]}")

    # List documents
    r5 = requests.get(
        "http://api.172-237-5-254.sslip.io/api/v1/documents/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    print(f"  List docs: {r5.status_code}")

except Exception as e:
    print(f"  Error: {e}")

# ═══════════════════════════════════
# 6. Check fresh errors
# ═══════════════════════════════════
time.sleep(3)
print("\n=== 6. Fresh errors ===")
out, _, _ = run("docker logs aihr-web --since 30s 2>&1 | grep -i 'error\\|exception' | head -10")
print(out if out else "(no errors!)")

ssh.close()
print("\nDone!")
