#!/usr/bin/env python3
"""Wait until a tenant has no uploading/parsing documents."""
import os
import time
import paramiko

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"
TENANT_NAME = os.getenv("AIHR_TENANT_NAME", "泰宇科技股份有限公司")

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
    cmd = f"docker exec aihr-db psql -U postgres -d aihr_prod -t -A -c '{escaped}'"
    return run(cmd)

out, err, rc = sql(f"SELECT id FROM tenants WHERE name = '{TENANT_NAME}' LIMIT 1;")
if rc != 0:
    print(err)
    raise SystemExit(1)

tenant_id = out.strip()
if not tenant_id:
    print("Tenant not found.")
    raise SystemExit(1)
print(f"Tenant: {TENANT_NAME} ({tenant_id})")

max_wait = 15 * 60
interval = 20
elapsed = 0

print("Waiting for tenant documents to finish processing...")
while elapsed <= max_wait:
    out, _, _ = sql(
        "SELECT status, COUNT(*) FROM documents "
        f"WHERE tenant_id = '{tenant_id}' GROUP BY status ORDER BY status;"
    )
    print(out if out else "(no docs)")
    counts = {"uploading": 0, "parsing": 0, "embedding": 0}
    for line in out.splitlines():
        if "uploading" in line:
            counts["uploading"] = int(line.split("|")[-1].strip())
        if "parsing" in line:
            counts["parsing"] = int(line.split("|")[-1].strip())
        if "embedding" in line:
            counts["embedding"] = int(line.split("|")[-1].strip())
    if counts["uploading"] == 0 and counts["parsing"] == 0 and counts["embedding"] == 0:
        print("All tenant documents processed.")
        break
    time.sleep(interval)
    elapsed += interval

if elapsed > max_wait:
    print("Timeout waiting for processing.")

ssh.close()
