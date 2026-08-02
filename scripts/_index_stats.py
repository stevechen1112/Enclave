from sqlalchemy import text
from app.db.session import SessionLocal
from app.models.document import DocumentChunk

db = SessionLocal()
print("chunk table", DocumentChunk.__tablename__)
print("chunks", db.query(DocumentChunk).count())
print("with embedding", db.query(DocumentChunk).filter(DocumentChunk.embedding.isnot(None)).count())

tid = "fd39fa1a-d45e-4e2c-89f1-19ab9945a1c5"
print("demo docs", db.execute(text("select count(*) from documents where tenant_id = :t"), {"t": tid}).scalar())
print("demo status", db.execute(text("select status, count(*) from documents where tenant_id = :t group by status"), {"t": tid}).fetchall())
print("tenants with docs", db.execute(text("select count(distinct tenant_id) from documents")).scalar())
print(
    "named production-ish",
    db.execute(
        text(
            """
            select name, count(*) over() as total
            from tenants
            where name in ('Demo Tenant', 'My Organization')
               or name not similar to '%(Test|Tenant [AB]|VSlice|Lineage|Revoke|Full Lifecycle|WikiEval|Smoketest|Integration)%'
            limit 20
            """
        )
    ).fetchall(),
)
db.close()
