#!/usr/bin/env python3
"""Validate and score an independently annotated Input truth corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.input_quality import (  # noqa: E402
    GeneralizationQualityThresholds,
    evaluate_generalization_quality,
)

SCHEMA_VERSION = "input-truth-corpus.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_truth_corpus(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    required_slices = payload.get("required_slices")
    cases = payload.get("cases")
    if not isinstance(required_slices, list) or not required_slices:
        raise ValueError("required_slices must be a non-empty list")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty list")
    seen: set[str] = set()
    for row in cases:
        case_id = str(row.get("id") or "")
        if not case_id or case_id in seen:
            raise ValueError("every case must have a unique non-empty id")
        seen.add(case_id)
        if row.get("ground_truth_verified"):
            annotation = row.get("annotation") or {}
            if not all(
                annotation.get(key)
                for key in ("annotator", "verified_at", "method")
            ):
                raise ValueError(
                    f"{case_id}: verified truth requires annotator, verified_at and method"
                )
        source = row.get("source") or {}
        relative = source.get("path")
        expected_hash = str(source.get("sha256") or "").lower()
        if relative:
            source_path = (path.parent / str(relative)).resolve()
            if not source_path.is_file():
                raise ValueError(f"{case_id}: source file does not exist")
            if not expected_hash or _sha256(source_path) != expected_hash:
                raise ValueError(f"{case_id}: source SHA-256 mismatch")
        elif row.get("ground_truth_verified") and not expected_hash:
            raise ValueError(
                f"{case_id}: verified truth requires an immutable source SHA-256"
            )
    return payload


def evaluate(path: Path) -> dict[str, Any]:
    corpus = load_truth_corpus(path)
    thresholds = GeneralizationQualityThresholds(**(corpus.get("thresholds") or {}))
    report = evaluate_generalization_quality(
        corpus["cases"],
        required_slices=corpus["required_slices"],
        thresholds=thresholds,
        requested_claim=str(corpus.get("requested_claim") or "semantic"),
    )
    report["corpus"] = {
        "id": corpus.get("corpus_id"),
        "schema_version": corpus["schema_version"],
        "manifest_sha256": _sha256(path),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.manifest.resolve())
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
