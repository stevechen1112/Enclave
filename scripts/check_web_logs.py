#!/usr/bin/env python3
"""查看最新 web 容器日誌"""
import paramiko

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username="root", key_filename=KEY_FILE, timeout=30)

# 發送一次登入請求後立即查看日誌
stdin, stdout, stderr = ssh.exec_command(
    'docker logs aihr-web --tail=20 2>&1 | grep -v "GET /health"',
    timeout=30
)
print(stdout.read().decode())
ssh.close()
