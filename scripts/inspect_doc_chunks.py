#!/usr/bin/env python3
"""Inspect chunk counts and sample text for specific documents."""
import paramiko

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

DOC_IDS = {
    "新人到職SOP": "b6df40b4-f9a2-4876-9164-8a4bff909f1d",
    "薪資條": "6c4655a2-a051-4e61-8059-786c1791d4e4",
}

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

for label, doc_id in DOC_IDS.items():
    print(f"=== {label} ({doc_id}) ===")
    out, _, _ = sql(
        f"SELECT filename, status, chunk_count, file_size FROM documents WHERE id = '{doc_id}';"
    )
    print(out)

    print("-- sample chunks (first 3) --")
    out, _, _ = sql(
        "SELECT chunk_index, LEFT(text, 200) FROM documentchunks "
        f"WHERE document_id = '{doc_id}' ORDER BY chunk_index ASC LIMIT 3;"
    )
    print(out if out else "(no chunks)")

    print("-- chunks containing key terms --")
    term = "文件" if label == "新人到職SOP" else "加班費"
    out, _, _ = sql(
        "SELECT chunk_index, LEFT(text, 200) FROM documentchunks "
        f"WHERE document_id = '{doc_id}' AND text ILIKE '%{term}%' ORDER BY chunk_index ASC LIMIT 5;"
    )
    print(out if out else "(no matches)")

ssh.close()
