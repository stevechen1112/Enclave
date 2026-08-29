#!/usr/bin/env python3
"""Replay the sealed Input I4 corpus and emit format-level quality evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.document_parser import DocumentParser
from app.services.input_quality import (
    evaluate_observations,
    provider_drift,
)
from app.services.parse_pipeline import _native_evidence_chunks

MANIFEST = ROOT / "artifacts" / "input" / "i4_quality_corpus_manifest.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "input" / "i4_quality_report.json"


def _normalise(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _locator_complete(extension: str, chunk) -> bool:
    if extension == ".docx":
        return bool(chunk.paragraph_index or chunk.section)
    if extension in {".xlsx", ".xls", ".csv"}:
        return bool(chunk.row_number and (chunk.worksheet or extension == ".csv") and chunk.cell_range if extension != ".csv" else chunk.row_number)
    if extension == ".pptx":
        return bool(chunk.slide_number and chunk.page)
    if extension in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic"}:
        return bool(chunk.bbox and not chunk.locator_fallback)
    if extension == ".pdf":
        return bool(chunk.page)
    return bool(chunk.section)


def _verify_manifest(manifest: dict) -> list[str]:
    errors: list[str] = []
    entries = manifest.get("entries") or []
    encoded = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != manifest.get("corpus_sha256"):
        errors.append("corpus_sha256 mismatch")
    for entry in entries:
        path = (ROOT / entry["path"]).resolve()
        try:
            path.relative_to(ROOT)
        except ValueError:
            errors.append(f"{entry['id']}: path escapes repository")
            continue
        if not path.is_file():
            errors.append(f"{entry['id']}: file missing")
            continue
        payload = path.read_bytes()
        if len(payload) != entry["bytes"]:
            errors.append(f"{entry['id']}: bytes mismatch")
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            errors.append(f"{entry['id']}: sha256 mismatch")
    return errors


def evaluate(manifest: dict) -> dict:
    manifest_errors = _verify_manifest(manifest)
    grouped: dict[str, list[dict]] = defaultdict(list)
    cases: list[dict] = []
    for entry in manifest.get("entries") or []:
        path = ROOT / entry["path"]
        extension = entry["extension"]
        file_type = DocumentParser.detect_file_type(path.name)
        try:
            text, metadata = DocumentParser.parse(str(path), file_type)
            chunks = _native_evidence_chunks(str(path), file_type, text, metadata)
            parse_success = True
            error = None
        except Exception as exc:  # noqa: BLE001 - evaluator must record parser crashes
            text, metadata, chunks = "", {}, []
            parse_success = False
            error = f"{type(exc).__name__}: {exc}"
        field_results = []
        for field_index, expected in enumerate(entry.get("expectations") or [], 1):
            expected_normalised = _normalise(expected)
            matching = [
                chunk
                for chunk in chunks
                if expected_normalised in _normalise(chunk.text)
            ]
            observation = {
                "id": f"{entry['id']}:field:{field_index}",
                "parse_success": parse_success,
                "expected": expected,
                "actual": text,
                "locator_complete": bool(matching) and all(
                    _locator_complete(extension, chunk) for chunk in matching
                ),
                "error": error,
            }
            grouped[extension].append(observation)
            field_results.append(
                {
                    "expected": expected,
                    "found": bool(matching),
                    "locator_complete": observation["locator_complete"],
                }
            )
        cases.append(
            {
                "id": entry["id"],
                "extension": extension,
                "category": entry["category"],
                "condition": entry["condition"],
                "sha256": entry["sha256"],
                "parse_success": parse_success,
                "parse_engine": metadata.get("parse_engine"),
                "quality_score": metadata.get("quality_score"),
                "ocr_confidence": metadata.get("ocr_confidence"),
                "structure_policy": metadata.get("structure_policy") or {},
                "provider_attempts": metadata.get("provider_attempts") or [],
                "field_results": field_results,
                "error": error,
            }
        )
    formats = {extension: evaluate_observations(extension, rows) for extension, rows in sorted(grouped.items())}
    # Every opened format gets a failure specimen proving the evaluator does not
    # equate parse completion with correctness.
    failure_samples = {
        extension: evaluate_observations(
            extension,
            [
                {
                    "id": f"{extension}:negative-control",
                    "parse_success": True,
                    "expected": "EXPECTED-FIELD-NOT-PRESENT",
                    "actual": "wrong content",
                    "locator_complete": False,
                    "error": "deliberate negative control",
                }
            ],
        )
        for extension in formats
    }
    passed = not manifest_errors and all(row["status"] == "PASS" for row in formats.values())
    return {
        "schema_version": 1,
        "phase": "Input I4",
        "run_id": str(uuid4()),
        "corpus_sha256": manifest.get("corpus_sha256"),
        "corpus_status": manifest.get("status"),
        "status": "PASS" if passed else "FAIL",
        "manifest_errors": manifest_errors,
        "formats": formats,
        "failure_samples": failure_samples,
        "cases": cases,
        "declared_gaps": manifest.get("declared_gaps") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = evaluate(manifest)
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        report["provider_drift"] = {
            extension: provider_drift(
                extension,
                baseline=baseline.get("formats", {}).get(extension, {}),
                candidate=current,
            )
            for extension, current in report["formats"].items()
        }
        if any(value["status"] != "PASS" for value in report["provider_drift"].values()):
            report["status"] = "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output), "formats": {key: value["status"] for key, value in report["formats"].items()}}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
