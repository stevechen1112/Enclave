import psycopg2

conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5435/enclave")
cur = conn.cursor()
cur.execute(
    """
    SELECT t.id, t.name, t.created_at FROM tenants t
    LEFT JOIN tenant_sidecar_bindings b ON b.tenant_id = t.id
    WHERE b.tenant_id IS NULL
    ORDER BY t.created_at DESC
    """
)
rows = cur.fetchall()
print(f"tenants without binding: {len(rows)}")
for r in rows[:10]:
    print(f"  {r[0]} {r[1]} created={r[2]}")
conn.close()
