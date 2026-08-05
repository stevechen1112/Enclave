"""比對文件與 chunks 的 tenant_id、tombstone、embedding 維度。"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import psycopg2

conn = psycopg2.connect(
    host="localhost", port=5435, dbname="enclave", user="postgres", password="postgres"
)
cur = conn.cursor()
cur.execute(
    "SELECT id, tenant_id, tombstoned_at FROM documents WHERE filename='000_nueip 合約(1).pdf'"
)
doc = cur.fetchone()
print("doc:", doc)
cur.execute(
    """
    SELECT c.chunk_index, c.tenant_id, (c.embedding IS NOT NULL),
           vector_dims(c.embedding) AS dims,
           json_extract_path_text(c.metadata_json, 'filename')
    FROM documentchunks c
    WHERE c.document_id = %s
    ORDER BY c.chunk_index
    """,
    (doc[0],),
)
for row in cur.fetchall():
    print(row)
