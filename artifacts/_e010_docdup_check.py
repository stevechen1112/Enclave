"""列出同名文件所有列與各自 chunk 統計。"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import psycopg2

conn = psycopg2.connect(
    host="localhost", port=5435, dbname="enclave", user="postgres", password="postgres"
)
cur = conn.cursor()
cur.execute(
    """
    SELECT d.id, d.tenant_id, d.status, d.tombstoned_at, d.created_at,
           (SELECT count(*) FROM documentchunks c WHERE c.document_id = d.id) AS nchunks,
           (SELECT count(*) FROM documentchunks c WHERE c.document_id = d.id AND c.embedding IS NOT NULL) AS nemb
    FROM documents d
    WHERE d.filename = '000_nueip 合約(1).pdf'
    ORDER BY d.created_at
    """
)
for row in cur.fetchall():
    print(row)
