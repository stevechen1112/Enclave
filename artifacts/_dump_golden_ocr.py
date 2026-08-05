import io, sys, os, json
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
manifest = json.load(open("testdata/golden/z1_scan_annotations/manifest.json", encoding="utf-8"))
out = {}
with eng.connect() as c:
    for e in manifest["entries"]:
        name = e["name"]
        rows = c.execute(text(
            "SELECT c.chunk_index, c.text FROM documents d JOIN documentchunks c ON c.document_id=d.id "
            "WHERE d.filename = :fn ORDER BY c.chunk_index"
        ), {"fn": name}).fetchall()
        # dedupe identical chunk texts (re-ingestion may leave duplicates across versions)
        seen, parts = set(), []
        for _, tx in rows:
            if tx and tx not in seen:
                seen.add(tx)
                parts.append(tx)
        out[e["id"]] = {"filename": name, "text": "\n----\n".join(parts)}

with open("artifacts/_golden_ocr_dump.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
for k, v in out.items():
    print(k, v["filename"], "chars:", len(v["text"]))
