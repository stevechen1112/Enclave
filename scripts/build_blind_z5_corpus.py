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

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = PROJECT_ROOT / "testdata" / "golden"
Z5_MANIFEST = PROJECT_ROOT / "artifacts" / "blind_z5" / "corpus_manifest.json"
Z5_QUESTIONS = GOLDEN_DIR / "z5_blind_questions.yaml"
Z5_SEAL = PROJECT_ROOT / "artifacts" / "blind_z5" / "seal.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_hashes(paths: list[Path]) -> set[str]:
    hashes: set[str] = set()
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stack = [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                for key in ("sha256", "content_hash", "file_hash"):
                    value = item.get(key)
                    if isinstance(value, str) and len(value) == 64:
                        hashes.add(value.lower())
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    return hashes


def build_corpus_manifest(
    corpus_dir: Path,
    output: Path,
    *,
    custodian: str,
    exclude_manifests: list[Path],
) -> None:
    """從語料目錄建立 corpus manifest。"""
    if not corpus_dir.exists():
        print(f"ERROR: corpus dir not found: {corpus_dir}")
        sys.exit(1)

    excluded_hashes = _manifest_hashes(exclude_manifests)
    documents = []
    for i, f in enumerate(sorted(corpus_dir.glob("*"))):
        if f.is_dir():
            continue
        sha = _sha256(f)
        if sha in excluded_hashes:
            print(f"ERROR: corpus overlaps an excluded manifest: {f.name}")
            sys.exit(1)
        documents.append({
            "id": f"z5-{i+1:03d}",
            "file": f.name,
            "sha256": sha,
            "size": f.stat().st_size,
            "extension": f.suffix.lower(),
        })

    if not documents:
        print("ERROR: a sealed corpus cannot be empty")
        sys.exit(1)

    snapshot_id = hashlib.sha256(
        "".join(d["sha256"] for d in documents).encode()
    ).hexdigest()[:16]

    manifest = {
        "corpus_snapshot_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": "Z5 hold-out corpus",
        "custodian": custodian,
        "exact_overlap_checked_against": [path.name for path in exclude_manifests],
        "documents": documents,
        "note": f"Built from {corpus_dir} ({len(documents)} files)",
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Corpus manifest written: {output} ({len(documents)} files, snapshot={snapshot_id})")


def freeze_gt(
    *,
    questions_path: Path,
    manifest_path: Path,
    seal_path: Path,
    custodian: str,
    attestation_path: Path,
    implementer: str | None,
) -> None:
    """Freeze non-empty independently attested GT and write an immutable hash seal."""
    if seal_path.exists():
        print(f"ERROR: seal already exists and cannot be overwritten: {seal_path}")
        sys.exit(1)
    if implementer and implementer.strip().casefold() == custodian.strip().casefold():
        print("ERROR: sealed holdout custodian must differ from the repair implementer")
        sys.exit(1)
    if not questions_path.exists() or not manifest_path.exists() or not attestation_path.exists():
        print("ERROR: questions, corpus manifest and independent attestation are required")
        sys.exit(1)

    content = questions_path.read_text(encoding="utf-8")
    payload = yaml.safe_load(content) or {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    questions = payload.get("questions") or []
    documents = manifest.get("documents") or []
    if len(questions) < 200:
        print(f"ERROR: platform sealed holdout requires at least 200 cases; found {len(questions)}")
        sys.exit(1)
    if not documents or not manifest.get("corpus_snapshot_id"):
        print("ERROR: corpus manifest is empty or unversioned")
        sys.exit(1)
    ids = [str(item.get("id") or "") for item in questions]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        print("ERROR: every sealed question must have a unique non-empty id")
        sys.exit(1)
    domains: dict[str, int] = {}
    mixed_language = 0
    for item in questions:
        domain = str(item.get("domain") or item.get("role") or "").strip()
        domains[domain] = domains.get(domain, 0) + 1
        if item.get("mixed_language") is True or item.get("language_profile") == "mixed":
            mixed_language += 1
    if len(domains) < 4 or min(domains.values()) < 50:
        print(f"ERROR: each declared domain requires at least 50 cases; counts={domains}")
        sys.exit(1)
    required_mixed = (len(questions) + 4) // 5
    if mixed_language < required_mixed:
        print(f"ERROR: at least 20% mixed-language/abbreviation cases required; found {mixed_language}/{len(questions)}")
        sys.exit(1)
    if "gt_frozen: false" not in content:
        print("ERROR: gt_frozen not found or already frozen")
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    content = content.replace("gt_frozen: false", "gt_frozen: true")
    content = content.replace('gt_frozen_at: ""', f'gt_frozen_at: "{now}"')
    content = content.replace("intent_frozen: false", "intent_frozen: true")

    questions_path.write_text(content, encoding="utf-8")
    seal = {
        "schema_version": 1,
        "split": "z5_holdout",
        "sealed_at": now,
        "custodian": custodian,
        "question_count": len(questions),
        "domain_counts": domains,
        "mixed_language_count": mixed_language,
        "corpus_snapshot_id": manifest["corpus_snapshot_id"],
        "corpus_manifest_sha256": _sha256(manifest_path),
        "questions_sha256": _sha256(questions_path),
        "attestation_sha256": _sha256(attestation_path),
        "first_run_status": "not_run",
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Z5 GT sealed at {now}: {seal_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Z5 hold-out corpus and freeze GT")
    ap.add_argument("--corpus-dir", type=Path, help="語料目錄路徑")
    ap.add_argument("--output", type=Path, default=Z5_MANIFEST, help="manifest 輸出路徑")
    ap.add_argument("--freeze", action="store_true", help="凍結 GT")
    ap.add_argument("--custodian", help="獨立題庫/語料保管者識別")
    ap.add_argument("--implementer", help="本輪修復實作者識別（不得與 custodian 相同）")
    ap.add_argument("--questions", type=Path, default=Z5_QUESTIONS)
    ap.add_argument("--manifest", type=Path, default=Z5_MANIFEST)
    ap.add_argument("--seal", type=Path, default=Z5_SEAL)
    ap.add_argument("--attestation", type=Path, help="獨立 GT/span 審核聲明")
    ap.add_argument("--exclude-manifest", action="append", type=Path, default=[])
    args = ap.parse_args()

    if args.freeze:
        if not args.custodian or not args.attestation:
            ap.error("--freeze requires --custodian and --attestation")
        freeze_gt(
            questions_path=args.questions,
            manifest_path=args.manifest,
            seal_path=args.seal,
            custodian=args.custodian,
            attestation_path=args.attestation,
            implementer=args.implementer,
        )
        return 0

    if args.corpus_dir:
        if not args.custodian:
            ap.error("--corpus-dir requires --custodian")
        build_corpus_manifest(
            args.corpus_dir,
            args.output,
            custodian=args.custodian,
            exclude_manifests=args.exclude_manifest,
        )
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
