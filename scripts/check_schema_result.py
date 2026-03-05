#!/usr/bin/env python3
"""Check actual DB columns for documents table and get fresh web errors"""
import paramiko

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username="root", key_filename=KEY_FILE, timeout=30)

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    return stdout.read().decode().strip(), stderr.read().decode().strip()

# 1. Check documents table columns
print("=== documents table columns ===")
out, _ = run("docker exec aihr-db psql -U postgres -d aihr_prod -c \"\\d documents\"")
print(out)

# 2. Check documentchunks table columns
print("\n=== documentchunks table columns ===")
out, _ = run("docker exec aihr-db psql -U postgres -d aihr_prod -c \"\\d documentchunks\"")
print(out)

# 3. Check users table columns  
print("\n=== users table columns ===")
out, _ = run("docker exec aihr-db psql -U postgres -d aihr_prod -c \"\\d users\"")
print(out)

# 4. Get FRESH web errors (since restart - last 50 lines)
print("\n=== Fresh web logs (last 50 lines of errors) ===")
out, _ = run("docker logs aihr-web --since 2m 2>&1 | grep -i 'error\\|traceback\\|500\\|exception\\|fail' | tail -50")
print(out if out else "(no errors in last 2 min)")

# 5. Make a quick test request and check logs
import requests
try:
    # Login first
    r = requests.post("http://api.172-237-5-254.sslip.io/api/v1/auth/login/access-token",
                       data={"username": "admin@example.com", "password": "mcWzOEha0w7zKH9u53yG7Q"}, timeout=10)
    token = r.json().get("access_token")
    
    # Try list documents
    r2 = requests.get("http://api.172-237-5-254.sslip.io/api/v1/documents/",
                       headers={"Authorization": f"Bearer {token}"}, timeout=10)
    print(f"\n=== List documents response: {r2.status_code} ===")
    print(r2.text[:500])
    
    # Try upload a txt file
    r3 = requests.post("http://api.172-237-5-254.sslip.io/api/v1/documents/upload",
                        headers={"Authorization": f"Bearer {token}"},
                        files={"file": ("test.txt", b"Hello world test content", "text/plain")},
                        timeout=10)
    print(f"\n=== Upload test.txt response: {r3.status_code} ===")
    print(r3.text[:500])
except Exception as e:
    print(f"Request error: {e}")

# 6. Check FRESH web errors after our test requests
import time
time.sleep(3)
print("\n=== Web errors after test requests ===")
out, _ = run("docker logs aihr-web --since 30s 2>&1 | tail -80")
print(out if out else "(no output)")

ssh.close()
