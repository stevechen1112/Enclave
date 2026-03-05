#!/usr/bin/env python3
"""
修復資料庫 schema：補齊缺失欄位
DB 現有欄位與 ORM model 不同步，需要 ALTER TABLE
"""
import paramiko

HOST = "172.237.5.254"
USER = "root"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY_FILE, timeout=30)
print("✅ SSH connected")

def run(cmd, timeout=60):
    """Execute SSH command"""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    rc = stdout.channel.recv_exit_status()
    return out, err, rc

# ═══ Step 1: 直接透過 SQL 補齊缺失的 tenants 欄位 ═══
print("\n[1] 補齊 tenants 表欄位...")

alter_sqls = [
    # Quota columns
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_users INTEGER;",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_documents INTEGER;",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_storage_mb INTEGER;",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS monthly_query_limit INTEGER;",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS monthly_token_limit INTEGER;",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS quota_alert_threshold FLOAT DEFAULT 0.8;",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS quota_alert_email VARCHAR;",
    # Branding columns
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS brand_name VARCHAR(100);",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS brand_logo_url VARCHAR(500);",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS brand_primary_color VARCHAR(7);",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS brand_secondary_color VARCHAR(7);",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS brand_favicon_url VARCHAR(500);",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS custom_domain VARCHAR(255) UNIQUE;",
    # Multi-region
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS region VARCHAR(10) NOT NULL DEFAULT 'ap';",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS data_residency_note TEXT;",
]

for sql in alter_sqls:
    out, err, rc = run(f'docker exec aihr-db psql -U postgres -d aihr_prod -c "{sql}"')
    col_name = sql.split("IF NOT EXISTS ")[1].split(" ")[0] if "IF NOT EXISTS" in sql else "?"
    status = "✅" if rc == 0 else "❌"
    print(f"  {status} {col_name}")

# ═══ Step 2: 補齊 users 表缺失欄位 ═══
print("\n[2] 檢查 users 表欄位...")
out, _, _ = run('docker exec aihr-db psql -U postgres -d aihr_prod -c "\\d users"')
print(f"  Users columns:\n{out}")

# 檢查是否有 department_id
if 'department_id' not in out:
    print("  Adding department_id...")
    run('docker exec aihr-db psql -U postgres -d aihr_prod -c "ALTER TABLE users ADD COLUMN IF NOT EXISTS department_id UUID REFERENCES departments(id);"')

# ═══ Step 3: 檢查 documents 表 ═══
print("\n[3] 檢查 documents 表欄位...")
out, _, _ = run('docker exec aihr-db psql -U postgres -d aihr_prod -c "\\d documents"')
print(f"  Documents columns:\n{out}")

# ═══ Step 4: 驗證修復後的 tenants 表 ═══
print("\n[4] 修復後 tenants 表結構...")
out, _, _ = run('docker exec aihr-db psql -U postgres -d aihr_prod -c "\\d tenants"')
print(out)

# ═══ Step 5: 重新嘗試建立租戶和超級管理員（直接 SQL） ═══
print("\n[5] 建立租戶和超級管理員（直接 SQL）...")

# 建立租戶
out, err, rc = run('''docker exec aihr-db psql -U postgres -d aihr_prod -c "
INSERT INTO tenants (id, name, plan, status, region)
VALUES (gen_random_uuid(), 'Demo Tenant', 'enterprise', 'active', 'ap')
ON CONFLICT DO NOTHING
RETURNING id, name;
"''')
print(f"  Tenant: {out}")

# 取得 tenant_id
out, _, _ = run('docker exec aihr-db psql -U postgres -d aihr_prod -t -c "SELECT id FROM tenants WHERE name=\'Demo Tenant\' LIMIT 1;"')
tenant_id = out.strip()
print(f"  Tenant ID: {tenant_id}")

if tenant_id:
    # 建立超級管理員 - 密碼需要 bcrypt hash
    # 先在 web 容器內生成 hash
    out, err, rc = run(f'''docker exec aihr-web python -c "
from app.core.security import get_password_hash
h = get_password_hash('mcWzOEha0w7zKH9u53yG7Q')
print(h)
"''')
    pw_hash = out.strip()
    print(f"  Password hash: {pw_hash[:20]}...")
    
    if pw_hash and pw_hash.startswith('$'):
        # 插入超級管理員
        out, err, rc = run(f'''docker exec aihr-db psql -U postgres -d aihr_prod -c "
INSERT INTO users (id, email, full_name, hashed_password, status, role, is_superuser, tenant_id)
VALUES (gen_random_uuid(), 'admin@aihr.local', 'Admin User', '{pw_hash}', 'active', 'owner', true, '{tenant_id}')
ON CONFLICT (email) DO NOTHING
RETURNING id, email;
"''')
        print(f"  User: {out}")
        if err and 'ERROR' in err:
            print(f"  Error: {err[:300]}")
    else:
        print(f"  ❌ Failed to hash password: {err[:300]}")

# ═══ Step 6: 最終驗證 ═══
print("\n[6] 最終驗證...")
out, _, _ = run('docker exec aihr-db psql -U postgres -d aihr_prod -c "SELECT email, status, is_superuser, role FROM users;"')
print(f"  Users: {out}")

# 重啟 web
print("\n[7] 重啟 web 服務...")
run("cd /opt/aihr && docker compose -f docker-compose.minimal.yml restart web")
import time; time.sleep(12)
out, _, _ = run("docker ps --filter name=aihr-web --format '{{.Status}}'")
print(f"  Web status: {out}")

ssh.close()
print("\n🏁 完成！")
