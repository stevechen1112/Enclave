#!/usr/bin/env python3
"""Validate operator-produced feedback/freshness/privacy/restore evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision


def validate_operator_evidence(payload: dict, *, image_digest: str, revision_id: str, manifest_hash: str):
    reasons = []
    if payload.get("image_digest") != image_digest:
        reasons.append("image_digest_mismatch")
    if str(payload.get("revision_id") or "") != revision_id or payload.get("manifest_hash") != manifest_hash:
        reasons.append("revision_or_manifest_mismatch")
    operator = payload.get("operator") or {}
    if not operator.get("id") or operator.get("role") not in {"operator", "sre", "qa"}:
        reasons.append("operator_identity_missing")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(operator.get("attestation_sha256") or "")):
        reasons.append("operator_attestation_missing")

    feedback = payload.get("feedback") or {}
    if int(feedback.get("sampled") or 0) < 1 or any(
        int(feedback.get(key) or 0) != 0
        for key in ("missing_owner", "missing_status", "missing_history")
    ):
        reasons.append("feedback_workflow_incomplete")

    freshness = payload.get("freshness") or {}
    if int(freshness.get("active_documents") or 0) < 1 or int(freshness.get("evaluated_documents") or 0) < int(freshness.get("active_documents") or 0):
        reasons.append("freshness_coverage_incomplete")
    if any(
        int(freshness.get(key) or 0) != 0
        for key in ("stale_answer_violations", "revoked_answer_violations", "connector_failure_answer_violations")
    ):
        reasons.append("invalid_source_remained_answerable")

    privacy = payload.get("trace_privacy") or {}
    total_traces = int(privacy.get("total_traces") or 0)
    required_sample = min(total_traces, 30)
    if total_traces < 1 or int(privacy.get("sampled_traces") or 0) < required_sample:
        reasons.append("trace_privacy_sample_incomplete")
    if int(privacy.get("sensitive_findings") or 0) != 0 or int(privacy.get("unauthorized_raw_content") or 0) != 0:
        reasons.append("trace_privacy_violation")

    recovery = payload.get("backup_restore") or {}
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(recovery.get("backup_digest") or "")):
        reasons.append("backup_digest_missing")
    if recovery.get("restore_smoke_status") != "PASS" or recovery.get("rollback_status") != "PASS":
        reasons.append("restore_or_rollback_not_passed")
    try:
        rto = float(recovery.get("rto_seconds"))
        target = float(recovery.get("target_rto_seconds"))
        if rto <= 0 or target <= 0 or rto > target:
            reasons.append("recovery_rto_missed")
    except (TypeError, ValueError):
        reasons.append("recovery_rto_unmeasured")
    return not reasons, reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--revision-id", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", default="artifacts/knowledge/operations_gate_last_run.json")
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", args.image_digest):
        raise SystemExit("image-digest must be sha256:<64 hex>")
    tenant_id = UUID(args.tenant_id)
    revision_id = UUID(args.revision_id)
    raw = Path(args.evidence).read_bytes()
    payload = json.loads(raw)

    db = SessionLocal()
    try:
        revision = db.query(KnowledgeBaseRevision).join(KnowledgeBase).filter(
            KnowledgeBaseRevision.id == revision_id,
            KnowledgeBase.tenant_id == tenant_id,
        ).first()
        if revision is None:
            raise SystemExit("revision not found for tenant")
        manifest_hash = revision.manifest_hash
    finally:
        db.close()

    evidence_ok, reasons = validate_operator_evidence(
        payload,
        image_digest=args.image_digest,
        revision_id=str(revision.id),
        manifest_hash=manifest_hash,
    )
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_knowledge_control.py", "-k", "feedback or freshness", "-q"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    checks = [
        {"name": "operator_evidence", "status": "PASS" if evidence_ok else "FAIL", "reasons": reasons},
        {"name": "feedback_freshness_regression", "status": "PASS" if proc.returncode == 0 else "FAIL"},
    ]
    status = "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL"
    report = {
        "schema_version": 1,
        "gate": "KB-OPS-01",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "revision_id": str(revision.id),
        "manifest_hash": manifest_hash,
        "image_digest": args.image_digest,
        "status": status,
        "evidence_digest": hashlib.sha256(raw).hexdigest(),
        "checks": checks,
        "test_output_tail": (proc.stdout + proc.stderr)[-4000:],
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(status)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
