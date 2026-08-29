"""Fail-closed verification for the sealed Input I0 corpus manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED_COVERAGE_AXES = {
    "document",
    "spreadsheet",
    "image",
    "audio",
    "video",
    "url",
    "connector",
}


def corpus_digest(entries: list[dict[str, Any]]) -> str:
    sealed = [
        {
            "id": str(entry.get("id") or ""),
            "path": str(entry.get("path") or ""),
            "sha256": str(entry.get("sha256") or "").lower(),
            "bytes": int(entry.get("bytes") or 0),
            "modalities": sorted(str(item) for item in entry.get("modalities") or []),
            "evidence_class": str(entry.get("evidence_class") or ""),
        }
        for entry in entries
    ]
    encoded = json.dumps(
        sorted(sealed, key=lambda item: item["id"]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_input_corpus_manifest(
    manifest: dict[str, Any], *, repository_root: Path
) -> dict[str, Any]:
    errors: list[str] = []
    root = repository_root.resolve()
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if manifest.get("contract_version") != "input-capabilities.v1":
        errors.append("contract_version is not input-capabilities.v1")
    if manifest.get("status") != "FROZEN_WITH_DECLARED_GAPS":
        errors.append("manifest status must be FROZEN_WITH_DECLARED_GAPS")

    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("entries must be a non-empty list")
        entries = []
    seen_ids: set[str] = set()
    verified_entries = 0
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("every entry must be an object")
            continue
        entry_id = str(entry.get("id") or "").strip()
        relative_path = str(entry.get("path") or "").strip()
        if not entry_id or entry_id in seen_ids:
            errors.append(f"entry id is missing or duplicated: {entry_id!r}")
        seen_ids.add(entry_id)
        if not relative_path:
            errors.append(f"entry {entry_id!r} has no path")
            continue
        candidate = (root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            errors.append(f"entry {entry_id!r} escapes repository root")
            continue
        if not candidate.is_file():
            errors.append(f"entry {entry_id!r} is missing: {relative_path}")
            continue
        payload = candidate.read_bytes()
        actual_hash = hashlib.sha256(payload).hexdigest()
        if actual_hash != str(entry.get("sha256") or "").lower():
            errors.append(f"entry {entry_id!r} sha256 mismatch")
        if len(payload) != entry.get("bytes"):
            errors.append(f"entry {entry_id!r} byte size mismatch")
        if not entry.get("modalities") or not entry.get("evidence_class"):
            errors.append(f"entry {entry_id!r} lacks evidence classification")
        verified_entries += 1

    expected_digest = corpus_digest(entries)
    if manifest.get("corpus_sha256") != expected_digest:
        errors.append("corpus_sha256 mismatch")

    coverage = manifest.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("coverage must be an object")
        coverage = {}
    missing_axes = sorted(REQUIRED_COVERAGE_AXES - set(coverage))
    if missing_axes:
        errors.append("missing coverage axes: " + ", ".join(missing_axes))
    for axis, declaration in coverage.items():
        if not isinstance(declaration, dict) or not declaration.get("level"):
            errors.append(f"coverage axis {axis!r} lacks a level")

    gaps = manifest.get("declared_gaps")
    if not isinstance(gaps, list) or not gaps:
        errors.append("declared_gaps must be a non-empty list")
    elif any(not isinstance(item, dict) or not item.get("id") for item in gaps):
        errors.append("every declared gap must have an id")

    return {
        "status": "PASS" if not errors else "FAIL",
        "contract_version": manifest.get("contract_version"),
        "corpus_sha256": expected_digest,
        "verified_entries": verified_entries,
        "coverage_axes": sorted(coverage),
        "declared_gap_count": len(gaps) if isinstance(gaps, list) else 0,
        "errors": errors,
    }
