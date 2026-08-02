"""Z1-1 — select ≥10 real scanned PDFs and write field-annotation YAML stubs.

Does NOT invent field values. Each YAML has empty `fields:` for a human (or a
later auto-fill pass) to complete. Selection prefers mid-size Chinese/English
scans that are not the known duplicate 「工作規則」PDF.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "testdata" / "golden" / "manifest.json"
INV = ROOT / "artifacts" / "corpus_inventory.json"
OUT_DIR = ROOT / "testdata" / "golden" / "z1_scan_annotations"
MANIFEST = OUT_DIR / "manifest.json"

TARGET = 12
SKIP_STEMS = {"工作規則", "c91aad3e"}  # known duplicate / already used in spike


def main() -> int:
    candidates = []
    # Prefer the already-stratified golden set (has kind=scanned).
    if GOLDEN.exists():
        g = json.loads(GOLDEN.read_text(encoding="utf-8"))
        for d in g.get("documents") or []:
            if str(d.get("kind") or "").lower() != "scanned":
                continue
            # Prefer the copied golden file if present, else source_path.
            copied = ROOT / "testdata" / "golden" / "files" / d.get("file", "")
            path = copied if copied.exists() else Path(d.get("source_path") or "")
            if not path.exists():
                continue
            if any(s in path.stem for s in SKIP_STEMS):
                continue
            size = int(d.get("size") or path.stat().st_size)
            if size < 80_000:  # skip tiny fixture stubs
                continue
            candidates.append({
                "path": str(path),
                "name": path.name,
                "size": size,
                "kind": "scanned",
                "pages": d.get("pages"),
                "genre": d.get("genre"),
                "golden_id": d.get("id"),
            })

    if len(candidates) < TARGET and INV.exists():
        inv = json.loads(INV.read_text(encoding="utf-8"))
        have = {c["path"] for c in candidates}
        for d in inv.get("documents") or []:
            if str(d.get("kind") or "").lower() != "scanned":
                continue
            path = Path(d.get("path") or "")
            if not path.exists() or str(path) in have:
                continue
            if any(s in path.stem for s in SKIP_STEMS):
                continue
            size = int(d.get("size") or 0)
            if size < 80_000 or size > 8_000_000:
                continue
            candidates.append({
                "path": str(path), "name": path.name, "size": size,
                "kind": "scanned", "pages": d.get("pages"),
            })

    # Diversify by genre then size.
    selected = []
    seen_genres: set[str] = set()
    for c in sorted(candidates, key=lambda x: (x.get("genre") or "", x["size"])):
        genre = str(c.get("genre") or "unknown")
        if genre in seen_genres and len(selected) < TARGET // 2:
            continue
        seen_genres.add(genre)
        selected.append(c)
        if len(selected) >= TARGET:
            break
    if len(selected) < TARGET:
        have = {s["path"] for s in selected}
        for c in candidates:
            if c["path"] in have:
                continue
            selected.append(c)
            if len(selected) >= TARGET:
                break

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for i, c in enumerate(selected, 1):
        doc_id = f"scan_{i:02d}"
        yml_path = OUT_DIR / f"{doc_id}.yaml"
        stub = {
            "id": doc_id,
            "source_path": c["path"],
            "filename": c["name"],
            "size_bytes": c["size"],
            "pdf_kind": c.get("kind") or "scanned",
            "annotator": "",
            "annotated_at": "",
            "fields": [
                # Human fills these. Examples of useful field shapes:
                # {"name": "title", "expected": "...", "page": 1}
                # {"name": "date", "expected": "YYYY-MM-DD", "page": 1}
                # {"name": "table_cell", "expected": "...", "page": 2, "bbox": null}
            ],
            "notes": "",
        }
        yml_path.write_text(
            yaml.safe_dump(stub, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        entries.append({"id": doc_id, "yaml": str(yml_path.relative_to(ROOT)), **c})

    manifest = {
        "gate": "Z1-1",
        "status": "SCAFFOLD",
        "selected": len(entries),
        "target": TARGET,
        "annotated": 0,
        "entries": entries,
        "next_step": (
            "Fill fields[] in each YAML (≥5 expected values per doc). "
            "Then run eval_parse_ablation.py for CV-RF-01b."
        ),
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(entries)} stubs under {OUT_DIR}")
    print(f"manifest: {MANIFEST}")
    for e in entries:
        print(f"  {e['id']}: {e['name']} ({e['size']//1024} KB)")
    return 0 if len(entries) >= 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
