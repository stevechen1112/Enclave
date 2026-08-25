#!/usr/bin/env python3
"""Validate independently captured browser acceptance for KB-UX-01.

The script never drives a browser and cannot manufacture acceptance.  It turns
an external runner's case-level evidence into a revision-bound release artifact
only when every required persona, negative authorization control and browser
surface has an explicit PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision

PERSONA_FLOWS = {
    "sales": {"login", "quote", "customer", "contract", "delivery", "source_expand", "logout_relogin"},
    "field": {"login", "equipment", "work_order", "sop", "incident", "source_expand", "logout_relogin"},
    "master": {"login", "approved_knowhow", "draft_boundary", "sop", "source_expand", "logout_relogin"},
    "newcomer": {"login", "steps", "follow_up", "access_denied", "source_expand", "logout_relogin"},
    "viewer": {"login", "query", "mutation_denied", "approval_denied", "source_expand", "logout_relogin"},
    "admin": {"login", "revision", "permission", "conflict", "approve", "release", "rollback", "logout_relogin"},
}
NEGATIVE_CONTROLS = {"deny", "cross_tenant", "cross_department", "kb_membership_conflict"}
SURFACES = {"refresh", "back", "empty", "403", "404", "mobile", "source_expand", "multiturn", "numeric_preservation", "admin_release_decision"}
AUTHZ_DIMENSIONS = {"system_role", "job_role", "department", "kb_membership", "source_acl"}
AUTHZ_PAIRS = {
    tuple(sorted((left, right)))
    for left in AUTHZ_DIMENSIONS
    for right in AUTHZ_DIMENSIONS
    if left < right
}


def _passed_names(rows) -> set[str]:
    return {
        str(row.get("name"))
        for row in (rows or [])
        if isinstance(row, dict)
        and row.get("status") == "PASS"
        and row.get("name")
        and isinstance(row.get("evidence_refs"), list)
        and row["evidence_refs"]
    }


def _covered_pairs(rows) -> set[tuple[str, str]]:
    covered = set()
    for row in rows or []:
        if not isinstance(row, dict) or row.get("status") != "PASS" or not row.get("evidence_refs"):
            continue
        dimensions = set((row.get("dimensions") or {}).keys()).intersection(AUTHZ_DIMENSIONS)
        for left in dimensions:
            for right in dimensions:
                if left < right:
                    covered.add(tuple(sorted((left, right))))
    return covered


def _release_binding_checks(evidence: dict) -> tuple[str, str, str, list[dict]]:
    """Validate the exact backend/frontend/deployment combination under test."""
    image_digest = str(evidence.get("image_digest") or "")
    frontend_image_digest = str(evidence.get("frontend_image_digest") or "")
    deployment_manifest_id = str(evidence.get("deployment_manifest_id") or "")
    checks = [
        {
            "name": "runtime_image",
            "status": "PASS" if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", image_digest) else "FAIL",
        },
        {
            "name": "frontend_image",
            "status": "PASS" if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", frontend_image_digest) else "FAIL",
        },
        {
            "name": "deployment_manifest",
            "status": "PASS" if re.fullmatch(r"dm-[0-9a-fA-F]{24}", deployment_manifest_id) else "FAIL",
        },
    ]
    return image_digest, frontend_image_digest, deployment_manifest_id, checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--revision-id", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", default="artifacts/knowledge/browser_acceptance_last_run.json")
    args = parser.parse_args()
    tenant_id = UUID(args.tenant_id); revision_id = UUID(args.revision_id)
    raw = Path(args.evidence).read_bytes()
    evidence = json.loads(raw)

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

    checks = []
    runner = evidence.get("runner") or {}
    independent = (
        bool(runner.get("id"))
        and runner.get("role") in {"qa", "product_owner", "external_tester"}
        and runner.get("independent_of_implementation") is True
        and re.fullmatch(r"[0-9a-fA-F]{64}", str(runner.get("attestation_sha256") or "")) is not None
    )
    checks.append({"name": "independent_runner", "status": "PASS" if independent else "FAIL"})
    image_digest, frontend_image_digest, deployment_manifest_id, binding_checks = _release_binding_checks(evidence)
    checks.extend(binding_checks)
    checks.append({
        "name": "revision_binding",
        "status": "PASS" if str(evidence.get("revision_id") or "") == str(revision.id)
        and str(evidence.get("manifest_hash") or "") == str(manifest_hash or "") else "FAIL",
    })

    persona_rows = evidence.get("personas") or {}
    for persona, required in PERSONA_FLOWS.items():
        passed = _passed_names(persona_rows.get(persona))
        missing = sorted(required - passed)
        checks.append({"name": f"persona:{persona}", "status": "PASS" if not missing else "FAIL", "missing": missing})

    negative_passed = _passed_names(evidence.get("negative_controls"))
    checks.append({"name": "negative_controls", "status": "PASS" if NEGATIVE_CONTROLS <= negative_passed else "FAIL",
                   "missing": sorted(NEGATIVE_CONTROLS - negative_passed)})
    pairwise = evidence.get("pairwise") or []
    covered_pairs = _covered_pairs(pairwise)
    missing_pairs = sorted(" × ".join(pair) for pair in AUTHZ_PAIRS - covered_pairs)
    pairwise_ok = len(pairwise) >= len(AUTHZ_PAIRS) and not missing_pairs
    checks.append({"name": "authorization_pairwise", "status": "PASS" if pairwise_ok else "FAIL",
                   "cases": len(pairwise), "missing_pairs": missing_pairs})
    surface_passed = _passed_names(evidence.get("surfaces"))
    checks.append({"name": "browser_surfaces", "status": "PASS" if SURFACES <= surface_passed else "FAIL",
                   "missing": sorted(SURFACES - surface_passed)})

    status = "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL"
    report = {
        "schema_version": 1,
        "gate": "KB-UX-01",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "revision_id": str(revision.id),
        "manifest_hash": manifest_hash,
        "image_digest": image_digest,
        "frontend_image_digest": frontend_image_digest,
        "deployment_manifest_id": deployment_manifest_id,
        "status": status,
        "evidence_digest": hashlib.sha256(raw).hexdigest(),
        "checks": checks,
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(status)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
