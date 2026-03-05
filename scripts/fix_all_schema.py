#!/usr/bin/env python3
"""
完整修復資料庫 schema — 補齊所有 ORM model 與 DB 之間的差異
"""
import paramiko
import time

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username="root", key_filename=KEY_FILE, timeout=30)
print("Connected\n")

def sql(statement):
    """Execute SQL in the DB container"""
    # Escape single quotes for shell
    escaped = statement.replace("'", "'\"'\"'")
    cmd = f"docker exec aihr-db psql -U postgres -d aihr_prod -c '{escaped}'"
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    rc = stdout.channel.recv_exit_status()
    return out, err, rc

def add_col(table, col, typ, extra=""):
    """Add column if not exists"""
    stmt = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ} {extra};"
    out, err, rc = sql(stmt)
    status = "OK" if rc == 0 else "ERR"
    print(f"  [{status}] {table}.{col} ({typ})")
    if rc != 0 and 'already exists' not in err:
        print(f"       {err[:100]}")

# ═══════════════════════════════════════════════════════════
# 1. documents 表 — 缺失欄位
# ═══════════════════════════════════════════════════════════
print("[1] documents 表")
add_col("documents", "file_size", "INTEGER")
add_col("documents", "chunk_count", "INTEGER")
add_col("documents", "quality_report", "JSONB")

# ═══════════════════════════════════════════════════════════
# 2. documentchunks 表 — 檢查缺失欄位
# ═══════════════════════════════════════════════════════════
print("\n[2] documentchunks 表")
add_col("documentchunks", "chunk_hash", "VARCHAR")
add_col("documentchunks", "vector_id", "VARCHAR")
add_col("documentchunks", "metadata_json", "JSONB", "DEFAULT '{}'")
# pgvector embedding column - check if extension exists first
sql("CREATE EXTENSION IF NOT EXISTS vector;")
add_col("documentchunks", "embedding", "vector(1024)")

# ═══════════════════════════════════════════════════════════
# 3. retrievaltraces 表 — 檢查欄位
# ═══════════════════════════════════════════════════════════
print("\n[3] retrievaltraces 表")
add_col("retrievaltraces", "latency_ms", "INTEGER")
add_col("retrievaltraces", "sources_json", "JSONB", "DEFAULT '{}'")

# ═══════════════════════════════════════════════════════════
# 4. usagerecords 表 — 檢查欄位
# ═══════════════════════════════════════════════════════════
print("\n[4] usagerecords 表")
add_col("usagerecords", "input_tokens", "INTEGER", "DEFAULT 0")
add_col("usagerecords", "output_tokens", "INTEGER", "DEFAULT 0")
add_col("usagerecords", "pinecone_queries", "INTEGER", "DEFAULT 0")
add_col("usagerecords", "embedding_calls", "INTEGER", "DEFAULT 0")
add_col("usagerecords", "latency_ms", "INTEGER", "DEFAULT 0")
add_col("usagerecords", "estimated_cost_usd", "FLOAT", "DEFAULT 0.0")

# ═══════════════════════════════════════════════════════════
# 5. 建立缺失的表
# ═══════════════════════════════════════════════════════════
print("\n[5] 建立缺失的表")

# chat_feedbacks
out, err, rc = sql("""
CREATE TABLE IF NOT EXISTS chat_feedbacks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    message_id UUID NOT NULL REFERENCES messages(id),
    user_id UUID NOT NULL REFERENCES users(id),
    rating SMALLINT NOT NULL,
    category VARCHAR(50),
    comment TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    UNIQUE(user_id, message_id)
);
""")
print(f"  chat_feedbacks: {'OK' if rc == 0 else err[:80]}")

# quotaalerts
out, err, rc = sql("""
CREATE TABLE IF NOT EXISTS quotaalerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    alert_type VARCHAR NOT NULL,
    resource VARCHAR NOT NULL,
    current_value INTEGER DEFAULT 0,
    limit_value INTEGER,
    usage_ratio FLOAT DEFAULT 0.0,
    message VARCHAR,
    notified BOOLEAN DEFAULT false,
    notified_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_quotaalerts_tenant_id ON quotaalerts(tenant_id);
""")
print(f"  quotaalerts: {'OK' if rc == 0 else err[:80]}")

# tenantsecurityconfigs
out, err, rc = sql("""
CREATE TABLE IF NOT EXISTS tenantsecurityconfigs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL UNIQUE,
    isolation_level VARCHAR DEFAULT 'standard',
    pinecone_index_name VARCHAR,
    pinecone_namespace VARCHAR,
    encryption_key_id VARCHAR,
    data_retention_days VARCHAR DEFAULT '365',
    ip_whitelist VARCHAR,
    require_mfa BOOLEAN DEFAULT false,
    audit_log_export_enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE
);
""")
print(f"  tenantsecurityconfigs: {'OK' if rc == 0 else err[:80]}")

# ═══════════════════════════════════════════════════════════
# 6. feature_flags 表 — 檢查欄位 (ARRAY columns)
# ═══════════════════════════════════════════════════════════
print("\n[6] feature_flags 表")
add_col("feature_flags", "rollout_percentage", "INTEGER", "DEFAULT 0")
add_col("feature_flags", "allowed_tenant_ids", "UUID[]")
add_col("feature_flags", "allowed_environments", "VARCHAR[]")
add_col("feature_flags", "metadata", "JSONB")

# ═══════════════════════════════════════════════════════════
# 7. departments 表 — 檢查欄位
# ═══════════════════════════════════════════════════════════
print("\n[7] departments 表")
add_col("departments", "parent_id", "UUID REFERENCES departments(id)")
add_col("departments", "is_active", "BOOLEAN", "DEFAULT true")
add_col("departments", "description", "VARCHAR")

# ═══════════════════════════════════════════════════════════
# 8. 驗證所有表
# ═══════════════════════════════════════════════════════════
print("\n[8] 驗證所有表")
out, _, _ = sql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;")
print(out)

# ═══════════════════════════════════════════════════════════
# 9. 重啟 web 服務
# ═══════════════════════════════════════════════════════════
print("\n[9] 重啟 web 服務...")
stdin, stdout, stderr = ssh.exec_command(
    f"cd /opt/aihr && docker compose -f docker-compose.minimal.yml restart web", timeout=60)
stdout.read()
time.sleep(15)

stdin, stdout, stderr = ssh.exec_command(
    "docker ps --filter name=aihr-web --format '{{.Status}}'", timeout=10)
status = stdout.read().decode().strip()
print(f"  Web status: {status}")

ssh.close()
print("\nDone!")
