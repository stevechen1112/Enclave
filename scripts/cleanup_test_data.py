import sys
from app.db.session import SessionLocal
from app.models.tenant import Tenant
from app.models.document import Document, DocumentChunk

TENANT_NAME = "泰宇科技股份有限公司"

def main():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == TENANT_NAME).first()
        if not tenant:
            print(f"Tenant not found: {TENANT_NAME}")
            return 1

        chunk_count = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.tenant_id == tenant.id)
            .delete(synchronize_session=False)
        )
        doc_count = (
            db.query(Document)
            .filter(Document.tenant_id == tenant.id)
            .delete(synchronize_session=False)
        )
        db.commit()
        print(f"Deleted {doc_count} documents and {chunk_count} chunks for tenant {TENANT_NAME}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
