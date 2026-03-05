#!/usr/bin/env python3
"""直接在伺服器上看完整錯誤"""
import paramiko

HOST = "172.237.5.254"
USER = "root"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY_FILE, timeout=30)
print("Connected")

# 先看 Tenant 模型有哪些 NOT NULL column
cmd = "docker exec aihr-web python -c \"from app.models.tenant import Tenant; import inspect; print(inspect.getsource(Tenant))\""
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
out = stdout.read().decode(); err = stderr.read().decode()
print("=== Tenant Model ===")
print(out if out else err[:1000])

# 查看 tenants 表結構
cmd2 = "docker exec aihr-db psql -U postgres -d aihr_prod -c \"\\d tenants\""
stdin, stdout, stderr = ssh.exec_command(cmd2, timeout=30)
out = stdout.read().decode(); err = stderr.read().decode()
print("\n=== tenants table ===")
print(out if out else err[:500])

# 測試最簡版本 — 直接 SQL 插入
cmd3 = '''docker exec aihr-db psql -U postgres -d aihr_prod -c "
INSERT INTO tenants (id, name, plan, status, region)
VALUES (gen_random_uuid(), 'Demo Tenant', 'enterprise', 'active', 'ap')
ON CONFLICT DO NOTHING
RETURNING id, name;
"'''
stdin, stdout, stderr = ssh.exec_command(cmd3, timeout=30)
out = stdout.read().decode(); err = stderr.read().decode()
print("\n=== Insert Tenant SQL ===")
print(out if out else err[:500])

ssh.close()
