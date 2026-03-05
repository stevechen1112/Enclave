#!/usr/bin/env python3
"""查看 web 容器最新錯誤日誌"""
import paramiko

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username="root", key_filename=KEY_FILE, timeout=30)

# 取得最近 50 行有 error/traceback/500 的日誌
cmds = [
    'docker logs aihr-web --tail=100 2>&1 | grep -A5 -i "error\\|traceback\\|500\\|exception" | tail -60',
    'docker logs aihr-web --tail=30 2>&1 | tail -25',
]

for cmd in cmds:
    print(f"$ {cmd[:80]}...")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    out = stdout.read().decode('utf-8', errors='replace')
    print(out)
    print("-" * 60)

ssh.close()
