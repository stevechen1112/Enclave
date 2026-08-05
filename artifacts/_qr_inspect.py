import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import psycopg2

conn = psycopg2.connect(host="localhost", port=5435, dbname="enclave",
                        user="postgres", password="postgres")
cur = conn.cursor()
cur.execute(
    "SELECT filename, quality_report FROM documents "
    "WHERE filename IN ('巨大機械9921深度研究報告.pdf', '113年營所稅申報書_E42八策.pdf') "
    "AND status='completed'"
)
for fn, qr in cur.fetchall():
    print("==", fn)
    print(json.dumps(qr, ensure_ascii=False, indent=1)[:1200])
    print()
