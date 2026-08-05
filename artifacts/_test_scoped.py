"""直接測試 scoped search：驗證 scope filter 與 cache 行為。"""
import io
import sys

sys.path.insert(0, "/code")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.core.authorization import AuthorizationContext
from app.services.retrieval_facade import get_retrieval_facade
import uuid

authz = AuthorizationContext(
    tenant_id=uuid.UUID(int=0), subject_id=uuid.UUID(int=1), is_superuser=True
)
# 用真實 tenant
import psycopg2
conn = psycopg2.connect(host="db", port=5432, dbname="enclave",
                        user="postgres", password="postgres")
cur = conn.cursor()
cur.execute("SELECT tenant_id FROM documents WHERE filename='113年營所稅申報書_E42八策.pdf' LIMIT 1")
tid = cur.fetchone()[0]
authz = AuthorizationContext(tenant_id=tid, subject_id=uuid.UUID(int=1), is_superuser=True)

facade = get_retrieval_facade()
q = "根據文件，納稅的公司名稱是什麼？"

print("--- scoped search (no cache) ---")
from app.services.kb_retrieval import KnowledgeBaseRetriever
res = KnowledgeBaseRetriever().search(
    tenant_id=tid, query=q, top_k=12, mode="semantic",
    filter_dict={"filename": "113年營所稅申報書_E42八策.pdf"},
    authz=authz, use_cache=False,
)
for r in res:
    md = r.get("metadata") or {}
    print(f"  fn={md.get('filename')!r} top_fn={r.get('filename')!r} "
          f"score={r.get('score'):.3f} text={r.get('content','')[:60]!r}")

print("--- scoped search (with cache, 1st) ---")
res2 = KnowledgeBaseRetriever().search(
    tenant_id=tid, query=q, top_k=12, mode="semantic",
    filter_dict={"filename": "113年營所稅申報書_E42八策.pdf"},
    authz=authz, use_cache=True,
)
print("  hits:", len(res2), "filenames:", { (r.get('metadata') or {}).get('filename') for r in res2 })

print("--- unscoped same query (cache read?) ---")
res3 = KnowledgeBaseRetriever().search(
    tenant_id=tid, query=q, top_k=12, mode="semantic", authz=authz, use_cache=True,
)
print("  hits:", len(res3), "filenames:", { (r.get('metadata') or {}).get('filename') for r in res3 })
