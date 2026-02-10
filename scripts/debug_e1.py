import sys, os
sys.path.insert(0, "/code")
os.environ.setdefault("POSTGRES_SERVER", "db")
os.environ.setdefault("REDIS_HOST", "redis")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@db:5432/unihr_saas")

from uuid import UUID

tenant_id = "75379488-6380-45ab-af06-1bd25e1dc7d0"
tid = UUID(tenant_id)

from app.services.structured_answers import RegistrationForm

reg = RegistrationForm.load(tid)
print(f"RegistrationForm loaded: {reg is not None}")
if reg:
    print(f"source_filename: {reg.source_filename}")
    print(f"text length: {len(reg.text)}")
    print(f"text preview: {reg.text[:300]}")
    cid = reg.company_id()
    print(f"company_id: {cid}")
else:
    # Debug: check documents table
    from app.db.session import SessionLocal
    from app.models.document import Document
    db = SessionLocal()
    docs = db.query(Document).filter(
        Document.tenant_id == tid,
        Document.filename.ilike("%變更登記%")
    ).all()
    print(f"\nDocuments matching '變更登記': {len(docs)}")
    for d in docs:
        print(f"  {d.id} | {d.filename} | {d.status}")
        from app.models.document_chunk import DocumentChunk
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == d.id).count()
        print(f"    chunks: {chunks}")
    db.close()
