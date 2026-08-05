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
    r = c.execute(text("SELECT metadata_json FROM documentchunks LIMIT 3")).fetchall()
    for row in r:
        print(list((row[0] or {}).keys()))
    r2 = c.execute(text(
        "SELECT metadata_json->>'filename' FROM documentchunks "
        "WHERE metadata_json->>'filename' IS NOT NULL LIMIT 3"
    )).fetchall()
    print("filename values:", [x[0] for x in r2])
