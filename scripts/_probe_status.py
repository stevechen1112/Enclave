import json, sys
sys.path.insert(0, "/code")
from sqlalchemy import create_engine, text
from app.config import settings
url = (f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
       f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")
eng = create_engine(url)
with eng.connect() as c:
    rows = c.execute(text("""
        SELECT filename, status, chunk_count,
               quality_report->>'parse_engine' AS engine,
               left(coalesce(error_message,''), 120) AS err, updated_at
        FROM documents
        WHERE status != 'deleted' AND tombstoned_at IS NULL
          AND (status != 'completed'
               OR quality_report->>'parse_engine' = 'native/text_fallback'
               OR filename IN ('b.pdf','employee_handbook.pdf','spec.pdf'))
        ORDER BY updated_at DESC
    """)).fetchall()
print(json.dumps(
    [dict(zip(["filename", "status", "chunks", "engine", "err", "updated_at"],
              [str(x) for x in r])) for r in rows],
    ensure_ascii=False, indent=1))
