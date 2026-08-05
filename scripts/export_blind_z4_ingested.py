"""Export Blind Z4 ingested chunk text from DB for GT annotation."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts" / "blind_z4"
UP = ART / "upload_result.json"
CAT = ART / "authoring_catalog.json"
OUT_DIR = ART / "ingested_text"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    up = json.loads(UP.read_text(encoding="utf-8"))["uploaded"]
    cat = {d["id"]: d for d in json.loads(CAT.read_text(encoding="utf-8"))["files"]}
    ids = [r["id"] for r in up if r.get("ok")]
    id_list = ",".join(f"'{i}'" for i in ids)
    sql = f"""
COPY (
  SELECT d.id::text, d.filename, c.chunk_index, c.text
  FROM documents d
  JOIN documentchunks c ON c.document_id = d.id
  WHERE d.id IN ({id_list})
  ORDER BY d.filename, c.chunk_index
) TO STDOUT WITH (FORMAT csv, HEADER true, FORCE_QUOTE *);
"""
    # Use simpler approach: one query per doc via JSON aggregate
    sql2 = f"""
SELECT json_agg(row_to_json(t) ORDER BY t.filename, t.chunk_index)
FROM (
  SELECT d.id::text AS id, d.filename, c.chunk_index, c.text
  FROM documents d
  JOIN documentchunks c ON c.document_id = d.id
  WHERE d.id IN ({id_list})
) t;
"""
    raw = subprocess.check_output(
        [
            "docker",
            "exec",
            "enclave-db-1",
            "psql",
            "-U",
            "postgres",
            "-d",
            "enclave",
            "-t",
            "-A",
            "-c",
            sql2,
        ],
        text=True,
        encoding="utf-8",
    ).strip()
    rows = json.loads(raw) if raw else []
    by_id: dict[str, list] = {}
    for r in rows:
        by_id.setdefault(r["id"], []).append(r)

    index = []
    for r in up:
        if not r.get("ok"):
            continue
        did = r["id"]
        chunks = by_id.get(did, [])
        text = "\n\n---\n\n".join(c["text"] or "" for c in sorted(chunks, key=lambda x: x["chunk_index"]))
        # sanitize filename for filesystem
        safe = re.sub(r'[<>:"/\\|?*]', "_", r["name"])[:120]
        out = OUT_DIR / f"{r.get('catalog_id','doc')}_{safe}.txt"
        out.write_text(text, encoding="utf-8")
        cid = r.get("catalog_id")
        meta = cat.get(cid, {})
        index.append(
            {
                "catalog_id": cid,
                "document_id": did,
                "filename": r["name"],
                "chunk_count": len(chunks),
                "char_count": len(text),
                "txt": str(out.relative_to(ROOT)).replace("\\", "/"),
                "client": meta.get("client_guess") or meta.get("client"),
            }
        )
        print(f"{cid} chunks={len(chunks)} chars={len(text)} {r['name'][:50]}")

    (ART / "ingested_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("wrote", OUT_DIR, "n=", len(index))


if __name__ == "__main__":
    main()
