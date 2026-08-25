#!/usr/bin/env python3
"""Produce revision-bound KB-REV-01 evidence."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.knowledge_release_gates import evaluate_revision_gate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--revision-id", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--output", default="artifacts/knowledge/revision_gate_last_run.json")
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", args.image_digest):
        raise SystemExit("image-digest must be sha256:<64 hex>")
    db = SessionLocal()
    try:
        result = evaluate_revision_gate(db, tenant_id=UUID(args.tenant_id), revision_id=UUID(args.revision_id))
        revision = result.pop("revision")
        report = {"schema_version": 1, "gate": "KB-REV-01", "generated_at": datetime.now(timezone.utc).isoformat(),
                  "revision_id": str(revision.id), "manifest_hash": revision.manifest_hash,
                  "image_digest": args.image_digest,
                  "status": result["status"], "checks": result["checks"]}
    finally:
        db.close()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report["status"])
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
