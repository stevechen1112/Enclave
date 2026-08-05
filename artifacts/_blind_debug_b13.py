import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import psycopg2

conn = psycopg2.connect(host="localhost", port=5435, dbname="enclave",
                        user="postgres", password="postgres")
cur = conn.cursor()
cur.execute(
    "SELECT c.chunk_index, c.text FROM documentchunks c "
    "JOIN documents d ON d.id=c.document_id "
    "WHERE d.filename='巨大機械9921深度研究報告.pdf' ORDER BY c.chunk_index"
)
rows = cur.fetchall()
full = "\n".join(t for _, t in rows)
for s in ["50%", "20%～30%", "佔集團營收", "2030"]:
    print(("OK  " if s in full else "MISS"), s)
print()
for i, t in rows:
    if "E-Bike" in t and ("營收" in t or "50" in t):
        print("chunk", i, ":", t[:300].replace("\n", " "))
