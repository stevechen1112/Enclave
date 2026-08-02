"""Z0-3: turn textual PDFs into image-only ("scanned") PDFs with automatic ground truth.

For every textual PDF in the golden manifest, the original text layer is captured as
ground truth, then each page is rasterised at --dpi and re-assembled into a PDF that
carries no text layer. Parsing the synthetic file and comparing against the stored
ground truth yields CER / coverage with zero manual annotation.

Caveat recorded in the manifest: synthetic scans lack the noise, skew and binding
shadows of real scans, so results must be cross-checked against the real scanned set.

Usage:
  python scripts/make_synthetic_scans.py --dpi 300
"""
import argparse
import hashlib
import json
import pathlib
import time

import fitz  # PyMuPDF

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "testdata" / "golden"
MANIFEST = GOLDEN / "manifest.json"
OUT_DIR = GOLDEN / "synthetic_scans"
OUT_MANIFEST = GOLDEN / "synthetic_manifest.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--max-pages", type=int, default=40, help="cap pages per document to bound runtime")
    ap.add_argument("--limit", type=int, default=0, help="only process the first N textual PDFs")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    targets = [d for d in manifest["documents"] if d["ext"] == ".pdf" and d["kind"] == "textual"]
    if args.limit:
        targets = targets[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    zoom = args.dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    records, t0 = [], time.time()
    for i, doc_meta in enumerate(targets, 1):
        src = GOLDEN / "files" / doc_meta["file"]
        print(f"[{i}/{len(targets)}] {src.name}", flush=True)
        try:
            src_doc = fitz.open(str(src))
        except Exception as e:
            print(f"    skip: {type(e).__name__}", flush=True)
            continue

        n_pages = min(src_doc.page_count, args.max_pages)
        ground_truth, out_doc = [], fitz.open()
        for pno in range(n_pages):
            page = src_doc[pno]
            ground_truth.append(page.get_text("text"))
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
            img_page.insert_image(page.rect, stream=pix.tobytes("png"))

        out_path = OUT_DIR / f"syn_{doc_meta['id']}_{src.stem[:40]}.pdf"
        out_doc.save(str(out_path), deflate=True, garbage=3)
        out_doc.close()
        src_doc.close()

        gt_text = "\n".join(ground_truth)
        gt_path = OUT_DIR / f"syn_{doc_meta['id']}.gt.txt"
        gt_path.write_text(gt_text, encoding="utf-8")

        records.append({
            "id": doc_meta["id"],
            "source_file": doc_meta["file"],
            "synthetic_file": out_path.name,
            "ground_truth_file": gt_path.name,
            "pages": n_pages,
            "gt_chars": len(gt_text),
            "gt_sha256": hashlib.sha256(gt_text.encode()).hexdigest(),
            "dpi": args.dpi,
            "synthetic_size": out_path.stat().st_size,
        })
        print(f"    -> {out_path.name}  pages={n_pages} gt_chars={len(gt_text)}", flush=True)

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "corpus_snapshot_id": manifest["corpus_snapshot_id"],
        "corpus": "synthetic_scan",
        "dpi": args.dpi,
        "caveat": "Synthetic scans lack real-scan noise/skew/binding shadows; "
                  "conclusions must be cross-checked on the real scanned set.",
        "count": len(records),
        "total_pages": sum(r["pages"] for r in records),
        "total_gt_chars": sum(r["gt_chars"] for r in records),
        "documents": records,
    }
    OUT_MANIFEST.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\ngenerated {len(records)} synthetic scans, {out['total_pages']} pages, "
          f"{out['total_gt_chars']} ground-truth chars in {time.time() - t0:.0f}s")
    print(f"written: {OUT_MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
