import io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from sqlalchemy import create_engine, text

eng = create_engine(
    "postgresql+psycopg2://%s:%s@localhost:5435/%s"
    % (os.environ.get("POSTGRES_USER", "postgres"),
       os.environ.get("POSTGRES_PASSWORD", "postgres"),
       os.environ.get("POSTGRES_DB", "enclave"))
)
with eng.connect() as c:
    rows = c.execute(text(
        "SELECT DISTINCT d.filename FROM documents d JOIN documentchunks c ON c.document_id=d.id "
        "WHERE c.text LIKE '%KWG%' OR c.text LIKE '%包裝清單%' OR c.text LIKE '%Watch GPS%'"
    )).fetchall()
    for r in rows:
        print(r[0])
