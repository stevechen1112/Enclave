"""直接呼叫 _semantic_search，繞過 rerank，看 scoped 實際命中幾筆。"""
import io
import sys

sys.path.insert(0, "/code")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import psycopg2
from app.services.kb_retrieval import KnowledgeBaseRetriever

conn = psycopg2.connect(host="db", port=5432, dbname="enclave",
                        user="postgres", password="postgres")
cur = conn.cursor()
cur.execute("SELECT tenant_id FROM documents WHERE filename='000_nueip 合約(1).pdf' LIMIT 1")
tid = cur.fetchone()[0]
conn.close()
print("tenant:", tid)

r = KnowledgeBaseRetriever()
q = "根據文件，出租系統的廠商名稱是什麼？"
res = r._semantic_search(tid, q, top_k=24, filter_dict={"filename": "000_nueip 合約(1).pdf"})
print(f"direct _semantic_search hits={len(res)}")
for it in res:
    txt = (it.get("content") or "")[:50].replace("\n", " ")
    print(f"  score={it.get('score'):.4f} chunk={it.get('chunk_index')} {txt!r}")
