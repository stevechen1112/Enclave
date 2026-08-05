"""Extract plain text samples from Blind Z3 corpus for ground-truth authoring."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

OUT = Path(__file__).resolve().parents[1] / "artifacts" / "blind_z3"
MANIFEST = OUT / "corpus_manifest.json"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def extract_docx(path: Path, limit: int = 12000) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    texts = [t.text for t in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t") if t.text]
    return re.sub(r"\s+", " ", "".join(texts))[:limit]


def extract_pdf(path: Path, limit: int = 12000) -> str:
    try:
        import pdfplumber
    except ImportError:
        return ""
    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:8]:
            t = page.extract_text() or ""
            if t.strip():
                chunks.append(t)
            if sum(len(c) for c in chunks) >= limit:
                break
    return re.sub(r"[ \t]+", " ", "\n".join(chunks))[:limit]


def main() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    extracts_dir = OUT / "extracts"
    extracts_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for i, f in enumerate(data["files"], 1):
        path = Path(f["path"])
        if not path.exists():
            continue
        text = ""
        if f["ext"] == ".docx":
            try:
                text = extract_docx(path)
            except Exception as exc:
                text = f"[docx extract error: {exc}]"
        elif f["ext"] == ".pdf":
            try:
                text = extract_pdf(path)
            except Exception as exc:
                text = f"[pdf extract error: {exc}]"
        out_name = f"{i:02d}_{f['client']}_{path.stem}"[:80] + ".txt"
        out_name = re.sub(r'[<>:\"/\\\\|?*]', "_", out_name)
        out_path = extracts_dir / out_name
        out_path.write_text(text or "[empty]", encoding="utf-8")
        index.append(
            {
                "id": f"D{i:02d}",
                "client": f["client"],
                "name": f["name"],
                "path": f["path"],
                "extract": str(out_path),
                "chars": len(text or ""),
                "has_text": bool(text and not text.startswith("[")),
            }
        )
        print(f"{i:02d} chars={len(text or '')} {f['name'][:60]}")

    (OUT / "extract_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"WROTE {OUT / 'extract_index.json'}")


if __name__ == "__main__":
    main()
