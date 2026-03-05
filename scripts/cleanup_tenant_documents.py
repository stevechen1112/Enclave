#!/usr/bin/env python3
"""Remove documents/chunks for a tenant by name to ensure a clean test dataset."""
import os
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

print(f"Tenant name: {TENANT_NAME}")

out, err, rc = sql(f"SELECT id FROM tenants WHERE name = '{TENANT_NAME}' LIMIT 1;")
if rc != 0:
    print(err)
    raise SystemExit(1)

tenant_id = out.strip()
if not tenant_id:
    print("Tenant not found.")
    raise SystemExit(1)
print(f"Tenant id: {tenant_id}")

# Delete chunks first, then documents
print("Deleting documentchunks...")
_, err, rc = sql(f"DELETE FROM documentchunks WHERE tenant_id = '{tenant_id}';")
print("OK" if rc == 0 else err[:120])

print("Deleting documents...")
_, err, rc = sql(f"DELETE FROM documents WHERE tenant_id = '{tenant_id}';")
print("OK" if rc == 0 else err[:120])

ssh.close()
