"""清除 e2e 測試租戶殘留文件（tombstone），恢復 FD-DELIVER 閘門。

範圍：測試租戶（WikiEval / Tenant A / Tenant B / VSlice Tenant / Lineage Tenant）
下所有非刪除文件。這些租戶由 e2e 腳本動態建立，無真實資料。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import psycopg2

TEST_TENANTS = ("WikiEval", "Tenant A", "Tenant B", "VSlice Tenant", "Lineage Tenant")

conn = psycopg2.connect(host="localhost", port=5435, dbname="enclave",
                        user="postgres", password="postgres")
cur = conn.cursor()
cur.execute(
    """
    SELECT d.id, d.filename, t.name FROM documents d
    JOIN tenants t ON t.id = d.tenant_id
    WHERE t.name = ANY(%s) AND d.status != 'deleted' AND d.tombstoned_at IS NULL
    """,
    (list(TEST_TENANTS),),
)
rows = cur.fetchall()
print(f"to tombstone: {len(rows)}")
for doc_id, fn, tname in rows:
    print(f"  {tname}: {fn} ({str(doc_id)[:8]})")

cur.execute(
    """
    UPDATE documents d SET status='deleted', tombstoned_at=now(), updated_at=now()
    FROM tenants t
    WHERE d.tenant_id = t.id AND t.name = ANY(%s)
      AND d.status != 'deleted' AND d.tombstoned_at IS NULL
    """,
    (list(TEST_TENANTS),),
)
print(f"tombstoned: {cur.rowcount}")
conn.commit()
conn.close()
