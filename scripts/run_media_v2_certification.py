#!/usr/bin/env python3
"""Build an immutable, fail-closed media-v2 pilot certification report."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.media_certification import build_media_certification_report  # noqa: E402


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--software-evidence", type=Path, required=True)
    parser.add_argument("--external-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("certification output must be a new immutable path")
    try:
        software = _read(args.software_evidence)
        external = _read(args.external_evidence) if args.external_evidence else None
        report = build_media_certification_report(
            software_evidence=software, external_evidence=external
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    report["software_evidence_sha256"] = hashlib.sha256(
        args.software_evidence.read_bytes()
    ).hexdigest()
    report["external_evidence_sha256"] = (
        hashlib.sha256(args.external_evidence.read_bytes()).hexdigest()
        if args.external_evidence
        else None
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["software_ready"] else 9


if __name__ == "__main__":
    raise SystemExit(main())
