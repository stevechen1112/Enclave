"""F2 — 存量文件 genre 回填（ADR-008）。

對所有非刪除文件依檔名＋首 chunk 內容片段重標 genre。
可在 worker 容器內或本機（設 POSTGRES_* 指向 DB）執行：

  docker compose exec -T worker python scripts/backfill_genre.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "artifacts" / "genre_backfill_last_run.json"


def main() -> int:
    from sqlalchemy import create_engine, text as sql_text

    import os
    url = os.getenv("DATABASE_URL") or (
        f"postgresql+psycopg2://{os.getenv('POSTGRES_USER', 'postgres')}"
        f":{os.getenv('POSTGRES_PASSWORD', 'postgres')}"
        f"@{os.getenv('POSTGRES_SERVER', 'localhost')}"
        f":{os.getenv('POSTGRES_PORT', '5435')}"
        f"/{os.getenv('POSTGRES_DB', 'enclave')}"
    )
    from app.services.genre_tagger import classify_genre

    eng = create_engine(url)
    t0 = time.time()
    updated = 0
    rows_out = []
    with eng.begin() as c:
        rows = c.execute(sql_text("""
            SELECT d.id, d.filename, d.genre,
                   (SELECT dc.text FROM documentchunks dc
                    WHERE dc.document_id = d.id ORDER BY dc.chunk_index LIMIT 1) AS sample
            FROM documents d
            WHERE d.status != 'deleted' AND d.tombstoned_at IS NULL
        """)).fetchall()
        for doc_id, filename, old_genre, sample in rows:
            new_genre = classify_genre(filename or "", sample)
            if new_genre != old_genre:
                c.execute(sql_text(
                    "UPDATE documents SET genre=:g WHERE id=:i"
                ), {"g": new_genre, "i": doc_id})
                updated += 1
            rows_out.append({"id": str(doc_id)[:8], "filename": filename,
                             "old": old_genre, "new": new_genre})

    report = {
        "gate": "genre-backfill",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": round(time.time() - t0, 1),
        "total": len(rows_out), "updated": updated,
        "rows": rows_out,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"total={len(rows_out)} updated={updated}")
    for r in rows_out:
        print(f"  {r['filename']}: {r['old']} -> {r['new']}")
    print("written:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
