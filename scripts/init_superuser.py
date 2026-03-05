#!/usr/bin/env python3
"""在容器內直接創建超級管理員（不依賴 scripts/initial_data.py 掛載）"""
import paramiko
import sys
import time

HOST = "172.237.5.254"
USER = "root"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"
PROJECT_DIR = "/opt/aihr"

def run_ssh(ssh, cmd, timeout=120):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    rc = stdout.channel.recv_exit_status()
    return out, err, rc

def main():
    print("🔧 建立超級管理員")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, key_filename=KEY_FILE, timeout=30)
    print("✅ SSH 連線成功")

    # 在 web 容器內執行 Python 程式碼
    init_code = '''
import sys
sys.path.insert(0, "/code")
from app.db.session import SessionLocal
from app.crud import crud_user, crud_tenant
from app.schemas.user import UserCreate
from app.schemas.tenant import TenantCreate
from app.config import settings

db = SessionLocal()

# 1. 建立租戶
tenant = crud_tenant.get_by_name(db, name="Demo Tenant")
if not tenant:
    tenant = crud_tenant.create(db, obj_in=TenantCreate(
        name="Demo Tenant",
        plan="enterprise",
        status="active"
    ))
    print(f"CREATED_TENANT: {tenant.name} | {tenant.id}")
else:
    print(f"EXISTING_TENANT: {tenant.name} | {tenant.id}")

# 2. 建立超級管理員
su_email = settings.FIRST_SUPERUSER_EMAIL
su_password = settings.FIRST_SUPERUSER_PASSWORD
print(f"SU_EMAIL: {su_email}")

user = crud_user.get_by_email(db, email=su_email)
if not user:
    user = crud_user.create(db, obj_in=UserCreate(
        email=su_email,
        password=su_password,
        tenant_id=tenant.id,
        role="owner",
        full_name="Admin User"
    ))
    user.is_superuser = True
    db.commit()
    db.refresh(user)
    print(f"CREATED_USER: {user.email} | {user.id} | superuser={user.is_superuser}")
else:
    print(f"EXISTING_USER: {user.email} | {user.id} | superuser={user.is_superuser}")

db.close()
print("DONE")
'''

    # 寫入暫存檔案到容器
    escaped_code = init_code.replace("'", "'\\''")
    
    # 先寫入伺服器暫存檔案
    sftp = ssh.open_sftp()
    with sftp.open("/tmp/init_superuser.py", "w") as f:
        f.write(init_code)
    sftp.close()
    print("✅ 初始化程式碼已上傳")

    # 複製到容器內並執行
    container_name = "aihr-web"
    out, err, rc = run_ssh(ssh, f"docker cp /tmp/init_superuser.py {container_name}:/code/init_superuser.py")
    print(f"  docker cp: rc={rc}")

    out, err, rc = run_ssh(ssh, f"docker exec {container_name} python /code/init_superuser.py")
    print(f"\n📋 執行結果:")
    if out:
        for line in out.split('\n'):
            print(f"  {line}")
    if rc != 0 and err:
        print(f"  ❌ Error: {err[:500]}")

    # 清理
    run_ssh(ssh, f"docker exec {container_name} rm -f /code/init_superuser.py")
    run_ssh(ssh, "rm -f /tmp/init_superuser.py")

    # 驗證登入
    print("\n📋 驗證登入...")
    out, err, rc = run_ssh(ssh,
        f'docker exec {container_name} python -c "'
        'from app.db.session import SessionLocal; '
        'from app.crud import crud_user; '
        'db = SessionLocal(); '
        'user = crud_user.get_by_email(db, email=\\"admin@aihr.local\\"); '
        'print(f\\"User: {{user.email}}, Superuser: {{user.is_superuser}}, Role: {{user.role}}\\") if user else print(\\"❌ User not found\\"); '
        'db.close()"')
    
    if out:
        print(f"  {out}")
    if rc != 0:
        print(f"  Error: {err[:300]}")

    ssh.close()
    print("\n🏁 完成")
    return 0

if __name__ == "__main__":
    sys.exit(main())
