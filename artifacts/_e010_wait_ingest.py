"""輪詢 nueip 合約入庫狀態直到 completed/failed，並檢查 chunk 數與人易科技。"""
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import psycopg2

DOC_ID = "b8bfc879-1373-4af5-a415-cb8f2706b4ec"

def check():
    conn = psycopg2.connect(
        host="localhost", port=5435, dbname="enclave", user="postgres", password="postgres"
    )
    cur = conn.cursor()
    cur.execute("SELECT status, chunk_count, error_message FROM documents WHERE id=%s", (DOC_ID,))
    row = cur.fetchone()
    nchunks = nemb = 0
    has_renyi = False
    if row:
        cur.execute(
            "SELECT count(*), coalesce(sum((embedding IS NOT NULL)::int),0), "
            "coalesce(bool_or(text LIKE '%%人易科技%%'), false) "
            "FROM documentchunks WHERE document_id=%s",
            (DOC_ID,),
        )
        nchunks, nemb, has_renyi = cur.fetchone()
    conn.close()
    return row, nchunks, nemb, has_renyi

for i in range(40):
    row, nchunks, nemb, has_renyi = check()
    if row:
        print(f"[{i}] status={row[0]} chunk_count={row[1]} err={row[2]} db_chunks={nchunks} emb={nemb} 人易={has_renyi}")
        if row[0] in ("completed", "failed"):
            break
    else:
        print(f"[{i}] doc not found")
    time.sleep(15)
