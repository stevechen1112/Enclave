import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import psycopg2

conn = psycopg2.connect(host="localhost", port=5435, dbname="enclave",
                        user="postgres", password="postgres")
cur = conn.cursor()
cur.execute(
    """
    SELECT d.filename, d.id, d.tenant_id, t.name AS tenant_name, d.created_at, d.uploaded_by
    FROM documents d LEFT JOIN tenants t ON t.id = d.tenant_id
    WHERE d.filename IN ('a.pdf','b.pdf','employee_handbook.pdf','spec.pdf')
      AND d.status != 'deleted' AND d.tombstoned_at IS NULL
    ORDER BY d.filename, d.created_at
    """
)
for row in cur.fetchall():
    print(row)
