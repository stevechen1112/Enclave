#!/usr/bin/env python
"""
P0-4：Z5 Hold-out 建立腳本

用途：
  1. 從新語料建立 corpus manifest
  2. 用獨立工具（pdfplumber/docx）提取 ground truth spans
  3. 產生題庫骨架
  4. 凍結 GT

使用方式：
  python scripts/build_blind_z5_corpus.py --corpus-dir <path> --output artifacts/blind_z5/corpus_manifest.json
  python scripts/build_blind_z5_corpus.py --freeze  # 凍結 GT

注意：
  - Z5 語料必須不同於 Z3/Z4
  - spans 必須對獨立提取的文本驗證（不用 Enclave chat 標註）
  - 凍結後不可修改題目或 GT
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = PROJECT_ROOT / "testdata" / "golden"
Z5_MANIFEST = PROJECT_ROOT / "artifacts" / "blind_z5" / "corpus_manifest.json"
Z5_QUESTIONS = GOLDEN_DIR / "z5_blind_questions.yaml"


def build_corpus_manifest(corpus_dir: Path, output: Path) -> None:
    """從語料目錄建立 corpus manifest。"""
    if not corpus_dir.exists():
        print(f"ERROR: corpus dir not found: {corpus_dir}")
        sys.exit(1)

    documents = []
    for i, f in enumerate(sorted(corpus_dir.glob("*"))):
        if f.is_dir():
            continue
        sha = hashlib.sha256(f.read_bytes()).hexdigest()
        documents.append({
            "id": f"z5-{i+1:03d}",
            "file": f.name,
            "path": str(f),
            "sha256": sha,
            "size": f.stat().st_size,
        })

    snapshot_id = hashlib.sha256(
        "".join(d["sha256"] for d in documents).encode()
    ).hexdigest()[:16]

    manifest = {
        "corpus_snapshot_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": "Z5 hold-out corpus",
        "documents": documents,
        "note": f"Built from {corpus_dir} ({len(documents)} files)",
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Corpus manifest written: {output} ({len(documents)} files, snapshot={snapshot_id})")


def freeze_gt() -> None:
    """凍結 Z5 GT — 更新 YAML 的 gt_frozen 欄位。"""
    if not Z5_QUESTIONS.exists():
        print(f"ERROR: questions file not found: {Z5_QUESTIONS}")
        sys.exit(1)

    content = Z5_QUESTIONS.read_text(encoding="utf-8")
    if "gt_frozen: false" not in content:
        print("ERROR: gt_frozen not found or already frozen")
        sys.exit(1)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    content = content.replace("gt_frozen: false", "gt_frozen: true")
    content = content.replace('gt_frozen_at: ""', f'gt_frozen_at: "{now}"')
    content = content.replace("intent_frozen: false", "intent_frozen: true")

    Z5_QUESTIONS.write_text(content, encoding="utf-8")
    print(f"Z5 GT frozen at {now}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Z5 hold-out corpus and freeze GT")
    ap.add_argument("--corpus-dir", type=Path, help="語料目錄路徑")
    ap.add_argument("--output", type=Path, default=Z5_MANIFEST, help="manifest 輸出路徑")
    ap.add_argument("--freeze", action="store_true", help="凍結 GT")
    args = ap.parse_args()

    if args.freeze:
        freeze_gt()
        return 0

    if args.corpus_dir:
        build_corpus_manifest(args.corpus_dir, args.output)
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())