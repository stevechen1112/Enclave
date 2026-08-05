import psycopg2
import os

conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5435/enclave")
cur = conn.cursor()
cur.execute(
    "SELECT b.tenant_id, t.name, b.ragflow_dataset_id IS NOT NULL, b.weknora_kb_id IS NOT NULL "
    "FROM tenant_sidecar_bindings b JOIN tenants t ON t.id = b.tenant_id"
)
rows = cur.fetchall()
print(f"bindings: {len(rows)}")
for r in rows:
    print(f"  tenant={r[0]} name={r[1]} has_dataset={r[2]} has_kb={r[3]}")
cur.execute("SELECT count(*) FROM tenants")
print(f"tenants total: {cur.fetchone()[0]}")
print("env RAGFLOW_DATASET_ID set:", bool(os.environ.get("RAGFLOW_DATASET_ID")))
conn.close()
