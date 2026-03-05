#!/usr/bin/env python3
"""SSH 到 Linode 伺服器並初始化資料庫"""
import paramiko
import sys
import time

HOST = "172.237.5.254"
USER = "root"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

commands = [
    "cd /opt/aihr && docker compose -f docker-compose.minimal.yml ps",
    "cd /opt/aihr && docker compose -f docker-compose.minimal.yml logs web --tail=30 2>&1 | tail -20",
    "echo '=== 檢查資料庫表 ==='",
    "cd /opt/aihr && docker compose -f docker-compose.minimal.yml exec -T db psql -U postgres -d aihr_prod -c '\\dt'",
    "echo '=== 檢查用戶 ==='",
    "cd /opt/aihr && docker compose -f docker-compose.minimal.yml exec -T db psql -U postgres -d aihr_prod -c 'SELECT email, is_active, is_superuser FROM users;'",
]

print(f"連線到 {HOST}...")
try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, key_filename=KEY_FILE, timeout=30)
    print(f"✅ SSH 連線成功")
    
    for cmd in commands:
        print(f"\n╔══════════════════════════════════════════════╗")
        print(f"║ $ {cmd:<42} ║")
        print(f"╚══════════════════════════════════════════════╝")
        
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
        output = stdout.read().decode('utf-8', errors='replace')
        error = stderr.read().decode('utf-8', errors='replace')
        
        if output:
            print(output)
        if error and "WARNING" not in error:
            print(f"Error: {error}")
        
        time.sleep(1)
    
    ssh.close()
    print("\n✅ 檢查完成")

except Exception as e:
    print(f"❌ 錯誤: {e}")
    sys.exit(1)
