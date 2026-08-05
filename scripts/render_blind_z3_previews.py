"""Render first pages of textless PDFs for visual GT annotation."""
from __future__ import annotations

import json
from pathlib import Path

import fitz

OUT = Path(__file__).resolve().parents[1] / "artifacts" / "blind_z3"
PREV = OUT / "page_previews"
IDX = OUT / "extract_index.json"


def main() -> None:
    PREV.mkdir(parents=True, exist_ok=True)
    idx = json.loads(IDX.read_text(encoding="utf-8"))
    empty = [x for x in idx if x["chars"] == 0]
    meta = []
    for x in empty:
        p = Path(x["path"])
        doc = fitz.open(p)
        pages = []
        for i in range(min(2, doc.page_count)):
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            out = PREV / f"{x['id']}_p{i + 1}.png"
            pix.save(str(out))
            pages.append(str(out))
        meta.append(
            {
                "id": x["id"],
                "name": x["name"],
                "client": x["client"],
                "pages": pages,
                "n_pages": doc.page_count,
            }
        )
        print(x["id"], "pages", doc.page_count, "->", len(pages), x["name"][:50])
    (PREV / "index.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("done", len(meta))


if __name__ == "__main__":
    main()
