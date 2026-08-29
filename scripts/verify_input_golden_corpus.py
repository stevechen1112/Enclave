#!/usr/bin/env python3
"""Verify, but never modify, the sealed Input I0 corpus manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.input_corpus_manifest import verify_input_corpus_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "artifacts" / "input" / "i0_golden_corpus_manifest.json",
    )
    args = parser.parse_args()
    if not args.manifest.is_file():
        print(f"missing manifest: {args.manifest}", file=sys.stderr)
        return 2
    result = verify_input_corpus_manifest(
        json.loads(args.manifest.read_text(encoding="utf-8")),
        repository_root=ROOT,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
