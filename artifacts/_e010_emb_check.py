"""檢查 E010 chunks 的 embedding 與 cosine 距離分布。"""
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
    SELECT c.id, c.chunk_index, (c.embedding IS NOT NULL) AS has_emb,
           length(c.text) AS len
    FROM documentchunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.filename = %s
    ORDER BY c.chunk_index, c.id
    """,
    ("000_nueip 合約(1).pdf",),
)
for row in cur.fetchall():
    print(row)
