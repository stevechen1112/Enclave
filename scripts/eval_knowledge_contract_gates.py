#!/usr/bin/env python3
"""Run deterministic contract tests and emit revision-bound gate evidence."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from app.db.session import SessionLocal
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision

GATES = {
    "KB-QSPEC-01": ("queryspec_gate_last_run.json", ["tests/test_query_plan.py"]),
    "KB-ROW-01": ("row_gate_last_run.json", ["tests/test_knowledge_engine.py", "tests/test_knowledge_control.py", "-k", "structured_resolver or aggregate or structured_retrieval"]),
    "KB-PROC-01": ("procedure_gate_last_run.json", ["tests/test_knowledge_engine.py", "-k", "procedure"]),
    "KB-EVIDENCE-01": ("evidence_gate_last_run.json", ["tests/test_knowledge_engine.py", "tests/test_source_verifier.py", "-k", "evidence or coverage or validator or source"]),
    "KB-AUTH-01": ("authority_gate_last_run.json", ["tests/test_knowledge_engine.py", "tests/test_knowledge_control.py", "-k", "authority or knowhow"]),
}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--tenant-id", required=True); ap.add_argument("--revision-id", required=True)
    ap.add_argument("--image-digest", required=True); args = ap.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", args.image_digest):
        raise SystemExit("image-digest must be sha256:<64 hex>")
    db = SessionLocal()
    try:
        rev = db.query(KnowledgeBaseRevision).join(KnowledgeBase).filter(
            KnowledgeBaseRevision.id == UUID(args.revision_id), KnowledgeBase.tenant_id == UUID(args.tenant_id)).first()
        if rev is None: raise SystemExit("revision not found for tenant")
        revision_id, manifest_hash = str(rev.id), rev.manifest_hash
    finally: db.close()
    overall = True
    for gate, (filename, pytest_args) in GATES.items():
        proc = subprocess.run([sys.executable, "-m", "pytest", *pytest_args, "-q"], cwd=ROOT, text=True, capture_output=True, check=False)
        status = "PASS" if proc.returncode == 0 else "FAIL"; overall = overall and proc.returncode == 0
        report = {"schema_version": 1, "gate": gate, "generated_at": datetime.now(timezone.utc).isoformat(),
                  "revision_id": revision_id, "manifest_hash": manifest_hash, "status": status,
                  "image_digest": args.image_digest,
                  "test_command": pytest_args, "output_tail": (proc.stdout + proc.stderr)[-8000:]}
        output = ROOT / "artifacts/knowledge" / filename; output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{gate}: {status}")
    return 0 if overall else 1


if __name__ == "__main__": raise SystemExit(main())
