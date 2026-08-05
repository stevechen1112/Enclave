import io
import sys

sys.path.insert(0, "/code")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import psycopg2

conn = psycopg2.connect(host="db", port=5432, dbname="enclave",
                        user="postgres", password="postgres")
cur = conn.cursor()
cur.execute("SELECT tenant_id FROM documents WHERE filename='113年營所稅申報書_E42八策.pdf' LIMIT 1")
tid = cur.fetchone()[0]
print("tenant:", tid)

# 直接打語意檢索的內部 SQL，繞過吞錯的外層
from app.models.document import Document, DocumentChunk
from app.db.session import SessionLocal
from app.tasks.document_tasks import embed_texts

emb = embed_texts(["根據文件，納稅的公司名稱是什麼？"], input_type="query")[0]
print("embedding len:", len(emb))

db = SessionLocal()
try:
    q = (
        db.query(DocumentChunk, DocumentChunk.embedding.cosine_distance(emb).label("d"))
        .join(Document, DocumentChunk.document_id == Document.id)
        .filter(
            DocumentChunk.tenant_id == tid,
            DocumentChunk.embedding.isnot(None),
            Document.tombstoned_at.is_(None),
        )
    )
    scoped = q.filter(
        DocumentChunk.metadata_json["filename"].astext == "113年營所稅申報書_E42八策.pdf"
    ).order_by("d").limit(12).all()
    print("scoped SQL rows:", len(scoped))
    for c, d in scoped[:3]:
        print("  ", c.chunk_index, (c.text or "")[:50].replace("\n", " "))
except Exception as e:
    print("SCOPED SQL ERROR:", type(e).__name__, e)
finally:
    db.close()
