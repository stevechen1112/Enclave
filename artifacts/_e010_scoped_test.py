"""直接測試 scoped 檢索對 E010 查詢的命中與分數。"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
sys.path.insert(0, "app")

from app.services.kb_retrieval import KnowledgeBaseRetriever

TENANT = None
from app.db.session import SessionLocal
from app.models.document import Document

db = SessionLocal()
doc = db.query(Document).filter(Document.filename == "000_nueip 合約(1).pdf").first()
tenant_id = doc.tenant_id
db.close()

r = KnowledgeBaseRetriever()
q = "根據文件，出租系統的廠商名稱是什麼？"
for mode in ("hybrid", "keyword", "semantic"):
    try:
        res = r.search(
            tenant_id, q, top_k=12, mode=mode, use_cache=False,
            filter_dict={"filename": "000_nueip 合約(1).pdf"},
        )
        print(f"== mode={mode} hits={len(res)}")
        for it in res:
            meta = it.get("metadata") or {}
            txt = (it.get("content") or "")[:60].replace("\n", " ")
            print(f"  score={it.get('score'):.4f} chunk={meta.get('chunk_index')} {txt!r}")
    except Exception as e:
        print(f"== mode={mode} ERROR {type(e).__name__}: {e}")
