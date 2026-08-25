#!/usr/bin/env python3
"""Non-persisting tenant shadow with before/after digest sentinels."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import func

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.authorization import AuthorizationContext
from app.db.session import SessionLocal, engine
from app.models.chat import Conversation, Message, RetrievalTrace
from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KnowledgeBaseRevision
from app.models.mka import KnowhowCardModel
from app.services.read_only_barrier import process_read_only
from app.services.retrieval_facade import get_retrieval_facade


def _digest(db, tenant_id):
    models = (Document, DocumentChunk, KnowledgeBaseRevision, KnowhowCardModel, Conversation, Message, RetrievalTrace)
    counts = {}
    for model in models:
        query = db.query(func.count(model.id))
        if hasattr(model, "tenant_id"):
            query = query.filter(model.tenant_id == tenant_id)
        counts[model.__tablename__] = int(query.scalar() or 0)
    body = json.dumps(counts, sort_keys=True)
    return {"counts": counts, "digest": hashlib.sha256(body.encode()).hexdigest()}


def _case_passes(result_ids: set[str], case: dict) -> tuple[bool, list[str]]:
    reasons = []
    expected = {str(value) for value in (case.get("expected_document_ids") or [])}
    forbidden = {str(value) for value in (case.get("forbidden_document_ids") or [])}
    minimum = max(int(case.get("min_results", 0)), 0)
    if case.get("expect_no_results") is True:
        if result_ids:
            reasons.append("expected_no_results")
    else:
        if len(result_ids) < max(minimum, 1):
            reasons.append("too_few_results")
        if not expected.issubset(result_ids):
            reasons.append("expected_documents_missing")
    if result_ids.intersection(forbidden):
        reasons.append("forbidden_document_returned")
    return not reasons, reasons


def _runtime_manifest_binding_errors(runtime_manifest: object, image_digest: str) -> list[str]:
    errors = []
    if not isinstance(runtime_manifest, dict) or runtime_manifest.get("image_digest") != image_digest:
        return ["backend_image_mismatch"]
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(runtime_manifest.get("frontend_image_digest") or "")):
        errors.append("frontend_image_missing")
    if not re.fullmatch(r"dm-[0-9a-fA-F]{24}", str(runtime_manifest.get("deployment_manifest_id") or "")):
        errors.append("deployment_manifest_missing")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--tenant-id", required=True); ap.add_argument("--queries", required=True)
    ap.add_argument("--revision-id", required=True)
    ap.add_argument("--image-digest", required=True)
    ap.add_argument("--runtime-manifest", required=True, help="JSON binding backend/frontend images, deployment manifest, models, prompt and flags")
    ap.add_argument("--output", default="artifacts/knowledge/shadow_last_run.json"); args = ap.parse_args()
    tenant_id = UUID(args.tenant_id); revision_id = UUID(args.revision_id)
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", args.image_digest or ""):
        raise SystemExit("image-digest must be a real sha256:<64 hex> digest")
    runtime_manifest = json.loads(Path(args.runtime_manifest).read_text(encoding="utf-8"))
    binding_errors = _runtime_manifest_binding_errors(runtime_manifest, args.image_digest)
    if binding_errors:
        raise SystemExit("runtime manifest release binding invalid: " + ", ".join(binding_errors))
    if not isinstance(runtime_manifest.get("model_manifest"), dict) or not runtime_manifest["model_manifest"]:
        raise SystemExit("runtime manifest requires a non-empty model_manifest")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(runtime_manifest.get("prompt_hash") or "")):
        raise SystemExit("runtime manifest requires a SHA-256 prompt_hash")
    if not isinstance(runtime_manifest.get("feature_flags"), dict):
        raise SystemExit("runtime manifest requires feature_flags")
    runtime_manifest["kb_revision_id"] = str(revision_id)
    cases_in = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    if not isinstance(cases_in, list) or len(cases_in) < 30 or not all(
        isinstance(case, dict)
        and isinstance(case.get("query"), str) and case["query"].strip()
        and isinstance(case.get("subject_id"), str)
        and isinstance(case.get("role_ids"), list)
        and isinstance(case.get("department_ids"), list)
        and (
            bool(case.get("expected_document_ids"))
            or case.get("expect_no_results") is True
        )
        for case in cases_in
    ):
        raise SystemExit("queries require >=30 ACL-bound tenant acceptance cases")
    negative_cases = sum(
        1 for case in cases_in
        if case.get("expect_no_results") is True or case.get("forbidden_document_ids")
    )
    distinct_subjects = {case["subject_id"] for case in cases_in}
    if negative_cases < 4 or len(distinct_subjects) < 2:
        raise SystemExit("shadow requires >=4 negative ACL cases and >=2 distinct subjects")
    db = SessionLocal()
    try:
        revision = db.query(KnowledgeBaseRevision).filter(
            KnowledgeBaseRevision.id == revision_id,
            KnowledgeBaseRevision.status.in_(["shadow", "active"]),
        ).first()
        if revision is None or revision.kb.tenant_id != tenant_id:
            raise SystemExit("revision is not a shadow/active revision for this tenant")
        manifest_hash = revision.manifest_hash
        runtime_manifest["kb_manifest_hash"] = manifest_hash
    finally:
        db.close()
    db = SessionLocal()
    try: before = _digest(db, tenant_id)
    finally: db.close()
    cases = []
    with process_read_only(engine):
        for case in cases_in:
            q = case["query"]
            authz = AuthorizationContext(
                tenant_id=tenant_id,
                subject_id=UUID(case["subject_id"]),
                role_ids=[str(value) for value in case["role_ids"]],
                department_ids=[UUID(value) for value in case["department_ids"]],
                group_ids=[UUID(value) for value in (case.get("group_ids") or [])],
                is_superuser=False,
                policy_revision=int(case.get("policy_revision", 1)),
            )
            minimum = max(int(case.get("min_results", 1)), 1)
            try:
                result = get_retrieval_facade().search(
                    authz=authz,
                    query=q,
                    top_k=max(8, minimum),
                    mode="keyword",
                    db=None,
                    scope={"kb_revision_id": str(revision_id)},
                )
                ids = sorted(str(r.get("document_id") or "") for r in result.results)
                passed, reasons = _case_passes(set(ids), case)
                cases.append({"query_hash": hashlib.sha256(q.encode()).hexdigest(), "status": "PASS" if passed else "FAIL",
                              "authz_fingerprint": authz.policy_fingerprint,
                              "result_count": len(ids), "result_digest": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
                              "reasons": reasons})
            except Exception as exc:  # noqa: BLE001 - shadow must record and fail closed
                cases.append({"query_hash": hashlib.sha256(q.encode()).hexdigest(), "status": "BLOCKED", "error_type": type(exc).__name__})
    db = SessionLocal()
    try: after = _digest(db, tenant_id)
    finally: db.close()
    unchanged = before == after
    report = {"schema_version": 1, "gate": "KB-SHADOW-01", "generated_at": datetime.now(timezone.utc).isoformat(),
              "tenant_id_hash": hashlib.sha256(str(tenant_id).encode()).hexdigest(), "read_only": True,
              "revision_id": str(revision_id), "manifest_hash": manifest_hash, "image_digest": args.image_digest,
              "runtime_manifest": runtime_manifest,
              "before": before, "after": after, "unexpected_writes": 0 if unchanged else 1,
              "status": "PASS" if unchanged and cases and all(c["status"] == "PASS" for c in cases) else "FAIL", "cases": cases}
    out = ROOT / args.output; out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report["status"]); return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
