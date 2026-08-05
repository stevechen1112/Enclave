import io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from sqlalchemy import create_engine, text

eng = create_engine(
    "postgresql+psycopg2://%s:%s@localhost:5435/%s"
    % (
        os.environ.get("POSTGRES_USER", "postgres"),
        os.environ.get("POSTGRES_PASSWORD", "postgres"),
        os.environ.get("POSTGRES_DB", "enclave"),
    )
)
needles = ["優利國際", "八策", "陳建宏", "陳有竹", "忠孝東路", "77557985", "0930168033",
           "勞動契約", "采統", "救國團", "心電心", "花總訓字", "114年3月3", "2026-02-02"]
with eng.connect() as c:
    rows = c.execute(text(
        "SELECT d.filename, c.text FROM documents d JOIN documentchunks c ON c.document_id=d.id "
        "WHERE d.filename LIKE '%nueip%' OR d.filename LIKE '%001_%'"
    )).fetchall()
    for fn, tx in rows:
        print("====", fn, "len", len(tx or ""))
        for n in needles:
            if n in (tx or ""):
                i = tx.index(n)
                print("  HIT", n, "->", tx[max(0,i-30):i+40].replace("\n", " "))
        print()
