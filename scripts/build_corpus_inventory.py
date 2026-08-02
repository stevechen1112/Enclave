"""Build a corpus inventory from the candidate file list.

Dedupes by (size, sha256 of first 64KB), classifies PDFs by text-layer presence,
and writes artifacts/corpus_inventory.json. This is the Z0-3 manifest skeleton.
"""
import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "artifacts" / "_corpus_candidates.txt"
OUT = ROOT / "artifacts" / "corpus_inventory.json"

SCANNED_CHARS_PER_PAGE = 50
SAMPLE_PAGES = 5


def sig_of(path: pathlib.Path, size: int) -> str:
    with open(path, "rb") as fh:
        head = fh.read(65536)
    return f"{size}:{hashlib.sha256(head).hexdigest()[:16]}"


def classify_pdf(path: pathlib.Path):
    """Return (pages, chars_per_page, kind) using pypdf on the first SAMPLE_PAGES pages."""
    from pypdf import PdfReader
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    n = min(pages, SAMPLE_PAGES)
    chars = 0
    for i in range(n):
        try:
            chars += len(reader.pages[i].extract_text() or "")
        except Exception:
            pass
    cpp = chars / max(n, 1)
    kind = "scanned" if cpp < SCANNED_CHARS_PER_PAGE else "textual"
    return pages, round(cpp, 1), kind


def main() -> None:
    paths = [pathlib.Path(line.strip()) for line in CANDIDATES.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    print(f"candidates: {len(paths)}", flush=True)

    entries = {}
    t0 = time.time()
    for idx, p in enumerate(paths):
        if idx % 200 == 0:
            print(f"progress {idx}/{len(paths)} elapsed={time.time() - t0:.0f}s unique={len(entries)}", flush=True)
        try:
            size = p.stat().st_size
            if size == 0:
                continue
            sig = sig_of(p, size)
        except OSError:
            continue
        if sig in entries:
            entries[sig]["copies"] += 1
            continue
        entry = {"path": str(p), "size": size, "ext": p.suffix.lower(), "copies": 1}
        if entry["ext"] == ".pdf":
            try:
                pages, cpp, kind = classify_pdf(p)
                entry.update(pages=pages, chars_per_page=cpp, kind=kind)
            except Exception as e:
                entry.update(kind="unreadable", error=type(e).__name__)
        entries[sig] = entry

    inv = list(entries.values())
    pdfs = [e for e in inv if e["ext"] == ".pdf"]
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "candidate_files": len(paths),
        "unique_documents": len(inv),
        "unique_pdf": len(pdfs),
        "pdf_textual": sum(1 for e in pdfs if e.get("kind") == "textual"),
        "pdf_scanned": sum(1 for e in pdfs if e.get("kind") == "scanned"),
        "pdf_unreadable": sum(1 for e in pdfs if e.get("kind") == "unreadable"),
        "office_docs": sum(1 for e in inv if e["ext"] != ".pdf"),
        "scanned_pages_total": sum(e.get("pages", 0) for e in pdfs if e.get("kind") == "scanned"),
    }
    OUT.write_text(json.dumps({"summary": summary, "documents": inv}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    print(f"written: {OUT}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
