#!/usr/bin/env python3
"""修復密碼 hash"""
import paramiko

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username="root", key_filename=KEY_FILE, timeout=30)
print("Connected")

def run(cmd, timeout=30):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return stdout.read().decode().strip(), stderr.read().decode().strip()

# 1. 看現在存在 DB 的 hash
out, _ = run('docker exec aihr-db psql -U postgres -d aihr_prod -t -c "SELECT hashed_password FROM users WHERE email=\'admin@aihr.local\';"')
print(f"Current hash in DB: [{out}]")

# 2. 在容器裡生成正確的 hash
out, err = run('''docker exec aihr-web python -c "
from app.core.security import get_password_hash
pw = 'mcWzOEha0w7zKH9u53yG7Q'
h = get_password_hash(pw)
print(h)
print(type(h))
print(len(h))
"''')
print(f"Generated hash: {out}")
if err:
    print(f"Stderr: {err[:500]}")

# 3. 用 ORM 方式更新 hash（避免 SQL 特殊字元問題）
# 寫一個 Python 腳本到容器裡
fix_script = '''
import sys
sys.path.insert(0, "/code")
from app.db.session import SessionLocal
from app.core.security import get_password_hash, verify_password
from app.models.user import User

db = SessionLocal()
user = db.query(User).filter(User.email == "admin@aihr.local").first()
if user:
    new_hash = get_password_hash("mcWzOEha0w7zKH9u53yG7Q")
    print(f"New hash: {new_hash[:30]}...")
    print(f"Hash length: {len(new_hash)}")
    user.hashed_password = new_hash
    db.commit()
    db.refresh(user)
    
    # Verify
    ok = verify_password("mcWzOEha0w7zKH9u53yG7Q", user.hashed_password)
    print(f"Verification: {ok}")
    print(f"Stored hash: {user.hashed_password[:30]}...")
else:
    print("User not found!")
db.close()
'''

# SFTP 上傳
sftp = ssh.open_sftp()
with sftp.open("/tmp/fix_pw.py", "w") as f:
    f.write(fix_script)
sftp.close()

run("docker cp /tmp/fix_pw.py aihr-web:/code/fix_pw.py")
out, err = run("docker exec aihr-web python /code/fix_pw.py")
print(f"\nFix result: {out}")
if err:
    print(f"Error: {err[:500]}")

# Cleanup
run("docker exec aihr-web rm -f /code/fix_pw.py")
run("rm -f /tmp/fix_pw.py")

ssh.close()
print("\nDone")
