#!/usr/bin/env python3
"""Inspect cloud LLM/embedding settings and vector processing status (masked output)."""
import paramiko

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

SHOW_KEYS = {
    "OPENAI_MODEL",
    "OPENAI_TEMPERATURE",
    "OPENAI_MAX_TOKENS",
    "VOYAGE_MODEL",
    "EMBEDDING_DIMENSION",
    "LLAMAPARSE_ENABLED",
    "LLAMAPARSE_API_KEY",
    "OPENAI_API_KEY",
    "VOYAGE_API_KEY",
}

MASK_KEYS = {"LLAMAPARSE_API_KEY", "OPENAI_API_KEY", "VOYAGE_API_KEY"}

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

print("=== Cloud .env (masked) ===")
raw, err, rc = run("cat /opt/aihr/.env")
if rc != 0:
    print(err)
else:
    env = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

    for k in sorted(SHOW_KEYS):
        if k in env:
            v = env[k]
            if k in MASK_KEYS and v:
                v = v[:4] + "..." + v[-4:]
            print(f"{k}={v}")
        else:
            print(f"{k}=(missing)")

print("\n=== Web container env (masked) ===")
raw, _, _ = run("docker exec aihr-web env")
web_env = {}
for line in raw.splitlines():
    if "=" not in line:
        continue
    k, v = line.split("=", 1)
    if k in SHOW_KEYS:
        web_env[k] = v
for k in sorted(SHOW_KEYS):
    if k in web_env:
        v = web_env[k]
        if k in MASK_KEYS and v:
            v = v[:4] + "..." + v[-4:]
        print(f"{k}={v}")
    else:
        print(f"{k}=(missing)")

print("\n=== Vector processing status ===")
print("Documents by status:")
out, _, _ = sql("SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY status;")
print(out)

print("\nDocument chunks:")
out, _, _ = sql("SELECT COUNT(*) AS total_chunks, SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) AS embedded_chunks FROM documentchunks;")
print(out)

ssh.close()
