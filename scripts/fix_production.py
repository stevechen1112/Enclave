#!/usr/bin/env python3
"""
修復生產環境問題：
1. 將 .env.production 複製為 .env（讓 Pydantic 讀取）
2. 修復 customdomains 缺失表
3. 初始化超級管理員
4. 重啟 web 服務
"""
import paramiko
import sys
import time

HOST = "172.237.5.254"
USER = "root"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"
PROJECT_DIR = "/opt/aihr"

def run_ssh(ssh, cmd, timeout=120):
    """執行 SSH 命令並返回結果"""
    print(f"  $ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    rc = stdout.channel.recv_exit_status()
    if out:
        for line in out.split('\n')[:15]:
            print(f"    {line}")
        if out.count('\n') > 15:
            print(f"    ... ({out.count(chr(10))} lines total)")
    if rc != 0 and err:
        # Filter out docker compose warnings
        real_errors = [l for l in err.split('\n') if 'level=warning' not in l and 'obsolete' not in l]
        if real_errors:
            for line in real_errors[:5]:
                print(f"    ⚠ {line}")
    return out, err, rc


def main():
    print(f"🔧 修復生產環境 ({HOST})")
    print("=" * 60)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(HOST, username=USER, key_filename=KEY_FILE, timeout=30)
        print("✅ SSH 連線成功\n")
    except Exception as e:
        print(f"❌ SSH 連線失敗: {e}")
        return 1

    # ═══ Step 1: 修復 .env 文件 ═══
    print("╔══════════════════════════════════════════════╗")
    print("║  Step 1: 修復 .env 文件                      ║")
    print("╚══════════════════════════════════════════════╝")
    
    # 檢查 .env.production 是否存在
    out, _, rc = run_ssh(ssh, f"cat {PROJECT_DIR}/.env.production | head -5")
    if rc != 0:
        print("  ❌ .env.production 不存在，跳過")
    else:
        # 複製 .env.production 為 .env
        run_ssh(ssh, f"cp {PROJECT_DIR}/.env.production {PROJECT_DIR}/.env")
        print("  ✅ .env.production → .env 複製完成")
    print()

    # ═══ Step 2: 修復 Alembic 遷移（customdomains 表） ═══
    print("╔══════════════════════════════════════════════╗")
    print("║  Step 2: 修復資料庫遷移                       ║")
    print("╚══════════════════════════════════════════════╝")
    
    # 直接在 DB 容器中創建缺失的表
    create_customdomains_sql = """
    CREATE TABLE IF NOT EXISTS customdomains (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id UUID NOT NULL REFERENCES tenants(id),
        domain VARCHAR NOT NULL UNIQUE,
        verification_token VARCHAR,
        verified BOOLEAN DEFAULT false,
        verified_at TIMESTAMP WITH TIME ZONE,
        ssl_provisioned BOOLEAN DEFAULT false,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
        updated_at TIMESTAMP WITH TIME ZONE
    );
    CREATE INDEX IF NOT EXISTS ix_customdomains_domain ON customdomains(domain);
    """
    
    out, err, rc = run_ssh(ssh, 
        f'cd {PROJECT_DIR} && docker compose -f docker-compose.minimal.yml exec -T db '
        f'psql -U postgres -d aihr_prod -c "{create_customdomains_sql}"')
    
    if 'CREATE TABLE' in out or 'already exists' in (out + err):
        print("  ✅ customdomains 表已建立")
    else:
        print(f"  ⚠ 結果: {out} {err}")
    print()

    # ═══ Step 3: 重啟 Web 服務（讀取新 .env） ═══
    print("╔══════════════════════════════════════════════╗")
    print("║  Step 3: 重啟 Web 服務                       ║")
    print("╚══════════════════════════════════════════════╝")
    
    run_ssh(ssh, f"cd {PROJECT_DIR} && docker compose -f docker-compose.minimal.yml restart web")
    print("  ⏳ 等待 Web 服務啟動...")
    time.sleep(15)
    
    # 檢查 web 容器狀態
    out, _, _ = run_ssh(ssh, f"cd {PROJECT_DIR} && docker compose -f docker-compose.minimal.yml ps web --format '{{{{.Status}}}}'")
    print(f"  Web 狀態: {out}")
    print()

    # ═══ Step 4: 初始化超級管理員 ═══
    print("╔══════════════════════════════════════════════╗")
    print("║  Step 4: 初始化超級管理員                     ║")
    print("╚══════════════════════════════════════════════╝")
    
    out, err, rc = run_ssh(ssh, 
        f"cd {PROJECT_DIR} && docker compose -f docker-compose.minimal.yml exec -T web "
        f"python scripts/initial_data.py", timeout=60)
    
    if rc == 0:
        print("  ✅ 超級管理員初始化完成")
    else:
        print(f"  ⚠ 初始化可能有問題，檢查日誌...")
        real_err = [l for l in err.split('\n') if 'level=warning' not in l and 'obsolete' not in l and l.strip()]
        for line in real_err[:10]:
            print(f"    {line}")
    print()

    # ═══ Step 5: 驗證 ═══
    print("╔══════════════════════════════════════════════╗")
    print("║  Step 5: 驗證修復結果                        ║")
    print("╚══════════════════════════════════════════════╝")
    
    # 5.1 檢查 users 表
    out, _, _ = run_ssh(ssh, 
        f"cd {PROJECT_DIR} && docker compose -f docker-compose.minimal.yml exec -T db "
        f"psql -U postgres -d aihr_prod -c \"SELECT email, status, is_superuser, role FROM users;\"")
    
    # 5.2 檢查 customdomains 表
    out, _, _ = run_ssh(ssh, 
        f"cd {PROJECT_DIR} && docker compose -f docker-compose.minimal.yml exec -T db "
        f"psql -U postgres -d aihr_prod -c \"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;\"")
    
    # 5.3 檢查 web 日誌（最後幾行）
    out, _, _ = run_ssh(ssh,
        f"cd {PROJECT_DIR} && docker compose -f docker-compose.minimal.yml logs web --tail=5 2>&1 | grep -v 'level=warning'")
    
    # 5.4 檢查環境變數載入
    out, _, _ = run_ssh(ssh,
        f"cd {PROJECT_DIR} && docker compose -f docker-compose.minimal.yml exec -T web "
        f"python -c \"from app.config import settings; print('SUPERUSER:', settings.FIRST_SUPERUSER_EMAIL); print('REDIS_HOST:', settings.REDIS_HOST); print('APP_ENV:', settings.APP_ENV)\"")
    
    print()
    print("=" * 60)
    print("🏁 修復完成！")
    
    ssh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
