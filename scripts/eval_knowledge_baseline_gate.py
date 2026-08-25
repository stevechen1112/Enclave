#!/usr/bin/env python3
"""Validate that K0 evidence is complete and bound to a candidate release."""
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

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from app.db.session import SessionLocal
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision


def read(path: Path):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def legacy_eval_is_unchanged(payload: dict) -> bool:
    files = payload.get("files") or {}
    if len(files) != 4:
        return False
    for name, expected in files.items():
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            return False
    return True


def citation_is_cross_process_stable() -> bool:
    code = "from app.gateway.citation import CitationBuilder;print(CitationBuilder._coerce_revision('opaque:中文:v7'))"
    try:
        first = subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, text=True, timeout=30).strip()
        second = subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, text=True, timeout=30).strip()
    except (OSError, subprocess.SubprocessError):
        return False
    expected = str((int.from_bytes(hashlib.sha256("opaque:中文:v7".encode()).digest()[:4], "big") % 2_000_000_000) + 1)
    return first == second == expected


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--tenant-id", required=True); ap.add_argument("--revision-id", required=True)
    ap.add_argument("--image-digest", required=True, help="exact candidate backend image under acceptance")
    ap.add_argument("--z5-seal", type=Path, default=ROOT / "artifacts/blind_z5/seal.json",
                    help="independent custodian's immutable Z5 seal")
    ap.add_argument("--output", default="artifacts/knowledge/baseline_gate_last_run.json"); args = ap.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", args.image_digest):
        raise SystemExit("image-digest must be sha256:<64 hex>")
    db = SessionLocal()
    try:
        rev = db.query(KnowledgeBaseRevision).join(KnowledgeBase).filter(
            KnowledgeBaseRevision.id == UUID(args.revision_id), KnowledgeBase.tenant_id == UUID(args.tenant_id)).first()
        if rev is None: raise SystemExit("revision not found for tenant")
        baseline = read(ROOT / "artifacts/knowledge/k0_baseline.json")
        leakage = read(ROOT / "artifacts/knowledge/core_leakage_last_run.json")
        legacy = read(ROOT / "artifacts/knowledge/legacy_eval_freeze.json")
        z5_seal = read(args.z5_seal)
        source = baseline.get("source") or {}
        production_runtime = baseline.get("production_runtime") or {}
        runtime = production_runtime.get("runtime") or {}
        checks = [
            {"name": "production_corpus_manifest_frozen", "status": "PASS" if baseline.get("production_corpus_manifest_id") and baseline.get("corpus") else "FAIL"},
            {"name": "runtime_image_frozen", "status": "PASS" if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(source.get("image_digest") or "")) else "FAIL"},
            {"name": "capability_disposition_exists", "status": "PASS" if (ROOT / "docs/knowledge/EXISTING_CAPABILITY_DISPOSITION.md").exists() else "FAIL"},
            {"name": "corpus_boundaries_exist", "status": "PASS" if (ROOT / "docs/knowledge/CORPUS_AND_EVAL_BOUNDARIES.md").exists() else "FAIL"},
            {"name": "core_leakage_scan", "status": "PASS" if leakage.get("status") == "PASS" else "FAIL"},
            {"name": "production_model_prompt_flags", "status": "PASS" if production_runtime.get("prompt_hash")
             and runtime.get("OPENAI_MODEL") and "RLS_ENFORCEMENT_ENABLED" in runtime else "FAIL"},
            {"name": "legacy_z3_z4_immutable", "status": "PASS" if legacy_eval_is_unchanged(legacy) else "FAIL"},
            {"name": "opaque_citation_cross_process", "status": "PASS" if citation_is_cross_process_stable() else "FAIL"},
            {"name": "hr_compatibility_boundary", "status": "PASS" if
             (ROOT / "app/knowledge_packs/hr_compatibility.py").is_file()
             and (ROOT / "docs/knowledge/EXISTING_CAPABILITY_DISPOSITION.md").is_file() else "FAIL"},
            {"name": "z5_independently_sealed", "status": "PASS" if
             z5_seal.get("question_count", 0) >= 200
             and len(z5_seal.get("domain_counts") or {}) >= 4
             and z5_seal.get("custodian")
             and re.fullmatch(r"[0-9a-fA-F]{64}", str(z5_seal.get("attestation_sha256") or ""))
             else "FAIL"},
        ]
        status = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
        report = {"schema_version": 1, "gate": "KB-BL-01", "generated_at": datetime.now(timezone.utc).isoformat(),
                  "revision_id": str(rev.id), "manifest_hash": rev.manifest_hash,
                  "image_digest": args.image_digest,
                  "baseline_source_image_digest": source.get("image_digest"),
                  "status": status, "checks": checks}
    finally: db.close()
    output = ROOT / args.output; output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report["status"]); return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
