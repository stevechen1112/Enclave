"""檢查 E010 文件在 DB 中的 chunks，找「人易」出現位置。"""
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
    SELECT c.chunk_index, c.text FROM documentchunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.filename = %s
    ORDER BY c.chunk_index
    """,
    ("000_nueip 合約(1).pdf",),
)
rows = cur.fetchall()
print(f"chunks={len(rows)}")
for idx, text in rows:
    text = text or ""
    hit = any(k in text for k in ("人易", "NUEiP", "廠商", "乙方", "出租", "甲方"))
    print(f"--- chunk {idx} len={len(text)}{' <<<' if hit else ''}")
    if hit:
        print(text[:800])
        print()
