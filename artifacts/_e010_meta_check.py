"""檢查 E010 文件各 chunk 的 metadata_json 是否含 filename。"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import psycopg2

conn = psycopg2.connect(
    host="localhost", port=5435, dbname="enclave", user="postgres", password="postgres"
)
cur = conn.cursor()
cur.execute(
    """
    SELECT c.chunk_index, c.metadata_json FROM documentchunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.filename = %s
    ORDER BY c.chunk_index
    """,
    ("000_nueip 合約(1).pdf",),
)
for idx, meta in cur.fetchall():
    m = meta if isinstance(meta, dict) else (json.loads(meta) if meta else {})
    print(f"chunk {idx}: keys={list(m.keys())} filename={m.get('filename')!r}")
