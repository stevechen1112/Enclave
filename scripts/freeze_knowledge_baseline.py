#!/usr/bin/env python3
"""Create a non-sensitive, reproducible K0 source/corpus baseline.

The artifact stores counts, stable ID/hash digests and configuration names only.
It never writes document text, user e-mail addresses, tokens or ACL subjects.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func

ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()


def _digest(values) -> str:
    body = "\n".join(sorted(str(v) for v in values))
    return hashlib.sha256(body.encode()).hexdigest()


def source_baseline(*, image_digest: str | None = None) -> dict:
    dirty = _git("status", "--porcelain=v1").splitlines()
    tracked = _git("ls-files").splitlines()
    eval_files = [p for p in tracked if p.startswith(("artifacts/blind_z", "test-materials/", "tests/fixtures/"))]
    deploy_files = [p for p in tracked if p.startswith(("app/", "frontend/", "nginx/", "compose/")) or p in {"Dockerfile", "docker-compose.prod.yml", "requirements.txt"}]
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "dirty_file_count": len(dirty),
        "dirty_manifest_hash": _digest(dirty),
        "tracked_manifest_hash": _digest(tracked),
        "deployment_manifest_hash": _digest(deploy_files),
        "deployment_file_count": len(deploy_files),
        "evaluation_manifest_hash": _digest(eval_files),
        "evaluation_file_count": len(eval_files),
        "image_digest": image_digest or os.getenv("ENCLAVE_IMAGE_DIGEST", "unavailable"),
        "model": os.getenv("OPENAI_MODEL", "configured-at-runtime"),
        "prompt_version": os.getenv("PROMPT_VERSION", "repository"),
        "feature_flag_names": sorted(k for k in os.environ if k.endswith(("_ENABLED", "_MODE"))),
    }


def corpus_baseline() -> dict:
    from app.db.session import SessionLocal
    from app.models.chat import RetrievalTrace
    from app.models.document import Document, DocumentChunk
    from app.models.knowledge_base import (
        KnowledgeBase,
        KnowledgeBaseMember,
        KnowledgeBaseRevision,
    )
    from app.models.mka import KnowhowCardModel
    from app.models.user import User

    db = SessionLocal()
    try:
        active_docs = db.query(Document).filter(Document.tombstoned_at.is_(None)).all()
        doc_tokens = [f"{d.id}:{getattr(d, 'version', 1)}:{d.content_hash or ''}:{d.status}:{d.knowledge_base_id or ''}" for d in active_docs]
        acl_tokens = [f"{m.kb_id}:{m.subject_type}:{m.role}:{m.effect}" for m in db.query(KnowledgeBaseMember).all()]
        return {
            "documents": db.query(func.count(Document.id)).scalar() or 0,
            "active_documents": len(active_docs),
            "chunks": db.query(func.count(DocumentChunk.id)).scalar() or 0,
            "knowledge_bases": db.query(func.count(KnowledgeBase.id)).scalar() or 0,
            "kb_revisions": db.query(func.count(KnowledgeBaseRevision.id)).scalar() or 0,
            "knowhow_cards": db.query(func.count(KnowhowCardModel.id)).scalar() or 0,
            "retrieval_traces": db.query(func.count(RetrievalTrace.id)).scalar() or 0,
            "users": db.query(func.count(User.id)).scalar() or 0,
            "active_document_digest": _digest(doc_tokens),
            "acl_policy_digest": _digest(acl_tokens),
        }
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="artifacts/knowledge/k0_baseline.json")
    ap.add_argument("--source-only", action="store_true")
    ap.add_argument("--image-digest", help="authoritative production image sha256:<64 hex>")
    ap.add_argument("--corpus-json", help="read-only production probe JSON; avoids connecting from this process")
    ap.add_argument("--runtime-json", help="non-secret production runtime manifest JSON")
    args = ap.parse_args()
    if args.image_digest and (
        not args.image_digest.startswith("sha256:") or len(args.image_digest) != 71
        or any(char not in "0123456789abcdefABCDEF" for char in args.image_digest[7:])
    ):
        raise SystemExit("image-digest must be sha256:<64 hex>")
    existing = {}
    output_path = ROOT / args.output
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            existing = {}
    implementation_source = source_baseline()
    data = {"schema_version": 1, "gate": "KB-BL-01", "generated_at": datetime.now(timezone.utc).isoformat(),
            "privacy": "counts_and_digests_only"}
    if args.corpus_json or args.runtime_json:
        data["construction_source"] = existing.get("construction_source") or existing.get("source") or implementation_source
        data["implementation_source"] = implementation_source
        data["source"] = {
            "deployment": "production",
            "image_digest": args.image_digest or "unavailable",
        }
    else:
        data["source"] = source_baseline(image_digest=args.image_digest)
    if not args.source_only:
        data["corpus"] = (
            json.loads(Path(args.corpus_json).read_text(encoding="utf-8"))
            if args.corpus_json else corpus_baseline()
        )
        data["production_corpus_manifest_id"] = "pcm-" + _digest([json.dumps(data["corpus"], sort_keys=True)])[:24]
    if args.runtime_json:
        data["production_runtime"] = json.loads(Path(args.runtime_json).read_text(encoding="utf-8"))
        data["source"]["runtime_manifest_hash"] = _digest([
            json.dumps(data["production_runtime"], sort_keys=True)
        ])
    out = output_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
