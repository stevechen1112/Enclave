#!/usr/bin/env python3
"""Wait until document processing completes (no uploading/parsing)."""
import paramiko
import time
import os

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

max_wait = 15 * 60
interval = 20
elapsed = 0

tenant_name = os.getenv("AIHR_TENANT_NAME", "").strip()
tenant_id = None

if tenant_name:
    out, _, _ = sql(f"SELECT id FROM tenants WHERE name = '{tenant_name}' LIMIT 1;")
    for line in out.splitlines():
        if "|" in line and "id" not in line:
            tenant_id = line.split("|")[0].strip()
            break
    if tenant_id:
        print(f"Filtering by tenant: {tenant_name} ({tenant_id})")
    else:
        print(f"Tenant not found: {tenant_name}. Falling back to all documents.")

print("Waiting for documents to finish processing...")
while elapsed <= max_wait:
    if tenant_id:
        out, _, _ = sql(
            f"SELECT status, COUNT(*) FROM documents WHERE tenant_id = '{tenant_id}' GROUP BY status ORDER BY status;"
        )
    else:
        out, _, _ = sql("SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY status;")
    print(out)
    # Quick parse
    counts = {"uploading": 0, "parsing": 0}
    for line in out.splitlines():
        if "uploading" in line:
            counts["uploading"] = int(line.split("|")[-1].strip())
        if "parsing" in line:
            counts["parsing"] = int(line.split("|")[-1].strip())
    if counts["uploading"] == 0 and counts["parsing"] == 0:
        print("All documents processed.")
        break
    time.sleep(interval)
    elapsed += interval

if elapsed > max_wait:
    print("Timeout waiting for processing.")

ssh.close()
