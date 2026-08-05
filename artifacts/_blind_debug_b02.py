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
    "WHERE d.filename='113年營所稅申報書_E42八策.pdf' ORDER BY c.chunk_index"
)
for i, t in cur.fetchall():
    print(f"--- chunk {i} ({len(t)} chars) ---")
    print(t[:350].replace("\n", " "))
    print()
