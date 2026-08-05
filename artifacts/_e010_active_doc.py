"""查看 active 文件的解析資訊與唯一 chunk 內容。"""
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
    SELECT column_name FROM information_schema.columns
    WHERE table_name='documents' ORDER BY ordinal_position
    """
)
cols = [r[0] for r in cur.fetchall()]
print("columns:", cols)
cur.execute(
    """
    SELECT * FROM documents
    WHERE id='3802cdc9-a404-4518-b052-089857ce92a0'
    """
)
row = cur.fetchone()
for c, v in zip(cols, row):
    s = str(v)
    print(f"{c}: {s[:200]}")
cur.execute(
    "SELECT chunk_index, length(text), left(text, 300) FROM documentchunks WHERE document_id='3802cdc9-a404-4518-b052-089857ce92a0'"
)
for r in cur.fetchall():
    print("chunk:", r[0], "len:", r[1])
    print(r[2])
