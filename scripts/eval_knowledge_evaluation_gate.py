#!/usr/bin/env python3
"""Require two distinct sealed first-runs at the external-beta threshold."""
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

from app.db.session import SessionLocal
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.models.knowledge_engine import EvaluationRun


def run_passes(summary: dict) -> tuple[bool, list[str]]:
    reasons = []
    total = int(summary.get("total") or 0)
    if total < 200:
        reasons.append("case_count_below_200")
    domain_distribution = summary.get("domain_distribution") or {}
    if len(domain_distribution) < 4:
        reasons.append("fewer_than_four_domains")
    for domain, denominator in domain_distribution.items():
        if int(denominator or 0) < 50:
            reasons.append(f"domain_case_count_below_50:{domain}")
    mixed = int((summary.get("language_profile_distribution") or {}).get("mixed") or 0)
    if total and mixed / total < .20:
        reasons.append("mixed_language_cases_below_20_percent")
    strict = summary.get("strict_assertions") or {}
    if (strict.get("rate") or 0) < .90:
        reasons.append("strict_pass_below_90_percent")
    if int(summary.get("critical_errors") or 0) != 0:
        reasons.append("critical_error_present")
    for domain, quality in (summary.get("domain_quality") or {}).items():
        if quality.get("denominator") and (quality.get("rate") or 0) < .85:
            reasons.append(f"domain_below_85_percent:{domain}")
    slots = summary.get("required_slot_coverage") or {}
    if not slots.get("denominator") or (slots.get("rate") or 0) < .95:
        reasons.append("required_slot_coverage_below_95_percent_or_unmeasured")
    return not reasons, reasons


def seal_passes(run: EvaluationRun) -> tuple[bool, list[str]]:
    runtime = run.runtime_manifest or {}
    seal = runtime.get("holdout_seal") or {}
    reasons = []
    if seal.get("questions_sha256") != run.question_hash:
        reasons.append("question_hash_not_bound_to_seal")
    if seal.get("corpus_manifest_sha256") != run.corpus_hash:
        reasons.append("corpus_hash_not_bound_to_seal")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(seal.get("attestation_sha256") or "")):
        reasons.append("independent_attestation_missing")
    custodian = str(seal.get("custodian") or "").strip().casefold()
    implementer = str(runtime.get("implementer") or "").strip().casefold()
    if not custodian:
        reasons.append("custodian_missing")
    if implementer and custodian == implementer:
        reasons.append("custodian_is_repair_implementer")
    return not reasons, reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True); parser.add_argument("--revision-id", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--output", default="artifacts/knowledge/evaluation_gate_last_run.json")
    args = parser.parse_args(); tenant_id = UUID(args.tenant_id); revision_id = UUID(args.revision_id)
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", args.image_digest):
        raise SystemExit("image-digest must be sha256:<64 hex>")
    db = SessionLocal()
    try:
        revision = db.query(KnowledgeBaseRevision).join(KnowledgeBase).filter(
            KnowledgeBaseRevision.id == revision_id, KnowledgeBase.tenant_id == tenant_id,
        ).first()
        if revision is None: raise SystemExit("revision not found for tenant")
        runs = db.query(EvaluationRun).filter(
            EvaluationRun.tenant_id == tenant_id,
            EvaluationRun.status == "completed",
            EvaluationRun.first_run.is_(True),
            EvaluationRun.split.ilike("sealed%"),
        ).order_by(EvaluationRun.completed_at.desc()).all()
        selected = []; corpus_hashes = set(); question_hashes = set()
        for run in runs:
            runtime = run.runtime_manifest or {}
            if str(runtime.get("kb_revision_id") or "") != str(revision.id):
                continue
            if str(runtime.get("kb_manifest_hash") or "") != str(revision.manifest_hash or ""):
                continue
            if str(runtime.get("image_digest") or "") != args.image_digest:
                continue
            if run.corpus_hash in corpus_hashes or run.question_hash in question_hashes:
                continue
            selected.append(run)
            corpus_hashes.add(run.corpus_hash); question_hashes.add(run.question_hash)
            if len(selected) == 2: break
        checks = []
        for run in selected:
            passed, reasons = run_passes(run.summary_json or {})
            sealed, seal_reasons = seal_passes(run)
            passed = passed and sealed
            reasons.extend(seal_reasons)
            checks.append({"run_id": str(run.id), "split": run.split, "status": "PASS" if passed else "FAIL",
                           "corpus_hash": run.corpus_hash, "reasons": reasons, "summary": run.summary_json})
        status = "PASS" if len(checks) == 2 and all(c["status"] == "PASS" for c in checks) else "FAIL"
        report = {"schema_version": 1, "gate": "KB-EVAL-01", "generated_at": datetime.now(timezone.utc).isoformat(),
                  "revision_id": str(revision.id), "manifest_hash": revision.manifest_hash, "status": status,
                  "image_digest": args.image_digest,
                  "required_distinct_holdouts": 2, "runs": checks}
    finally: db.close()
    output = ROOT / args.output; output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report["status"]); return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
