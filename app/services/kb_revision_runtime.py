"""Immutable KB revision creation, promotion and rollback."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import UUID

from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.models.knowledge_engine import KnowledgeBaseRevisionDocument
from app.models.knowledge_engine import KnowledgeRelease, RollbackPoint, RuntimeRelease
from app.models.kb_maintenance import DocumentVersion
from app.models.document import Document

LIFECYCLE = {"draft": {"candidate", "rejected"}, "candidate": {"shadow", "rejected"},
             "shadow": {"active", "rejected"}, "active": {"retired"}, "retired": set(), "rejected": set()}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class KBRevisionRuntime:
    def ensure_default_kb(self, db, *, tenant_id: UUID) -> KnowledgeBase:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.name == "Default Knowledge Base").first()
        if kb is None:
            kb = KnowledgeBase(tenant_id=tenant_id, name="Default Knowledge Base", description="由既有租戶文件建立，不複製原始內容", status="active", active_revision=0)
            db.add(kb); db.flush()
        return kb

    def snapshot_current_documents(self, db, *, tenant_id: UUID, kb: KnowledgeBase) -> list[DocumentVersion]:
        """Create missing immutable snapshots before the first revision.

        Existing DocumentVersion rows are reused.  Content text is assembled
        only for the snapshot and never copied back into the live document.
        """
        docs = db.query(Document).filter(Document.tenant_id == tenant_id, Document.tombstoned_at.is_(None), Document.status == "completed").all()
        versions: list[DocumentVersion] = []
        for doc in docs:
            version = int(doc.version or 1)
            snap = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id, DocumentVersion.version == version).first()
            if snap is None:
                text = "\n".join(
                    c.text or ""
                    for c in sorted(
                        (c for c in doc.chunks if int(c.document_revision or 1) == version),
                        key=lambda c: c.chunk_index,
                    )
                )
                snap = DocumentVersion(tenant_id=tenant_id, document_id=doc.id, version=version, filename=doc.filename,
                    file_path=doc.file_path, file_size=doc.file_size, file_type=doc.file_type, chunk_count=doc.chunk_count,
                    status=doc.status, quality_report=doc.quality_report, uploaded_by=doc.uploaded_by, content_snapshot=text)
                db.add(snap); db.flush()
            if doc.knowledge_base_id is None:
                doc.knowledge_base_id = kb.id
            versions.append(snap)
        db.flush()
        return versions
    def create_candidate(self, db, *, kb: KnowledgeBase, document_versions: Iterable[DocumentVersion], policy_revision: int = 1,
                         manifest_versions: Optional[dict] = None) -> KnowledgeBaseRevision:
        versions = sorted(list(document_versions), key=lambda d: (str(d.document_id), d.version))
        next_revision = max([r.revision for r in kb.revisions] or [0]) + 1
        members = [{"document_id": str(d.document_id), "document_version_id": str(d.id), "revision": d.version,
                    "content_hash": canonical_hash(d.content_snapshot or "")} for d in versions]
        manifest = {"documents": members, "versions": manifest_versions or {}, "policy_revision": policy_revision}
        rev = KnowledgeBaseRevision(kb_id=kb.id, revision=next_revision, status="candidate", policy_revision=policy_revision,
                                    manifest_hash=canonical_hash(manifest), manifest_json=manifest,
                                    index_namespace=f"kb:{kb.id}:r{next_revision}")
        db.add(rev); db.flush()
        for d, m in zip(versions, members):
            db.add(KnowledgeBaseRevisionDocument(tenant_id=kb.tenant_id, kb_revision_id=rev.id, document_id=d.document_id,
                document_version_id=d.id, document_revision=d.version, content_hash=m["content_hash"],
                acl_snapshot={}, policy_revision=policy_revision))
        db.flush()
        return rev

    def transition(self, revision: KnowledgeBaseRevision, target: str) -> None:
        if target not in LIFECYCLE.get(revision.status, set()):
            raise ValueError(f"invalid KB revision transition: {revision.status} -> {target}")
        revision.status = target

    def promote(self, db, *, kb: KnowledgeBase, revision: KnowledgeBaseRevision, gate_evidence: dict,
                runtime_manifest: Optional[dict] = None, gate_artifacts: Optional[dict] = None,
                created_by: Optional[UUID] = None) -> None:
        if revision.status != "shadow":
            raise ValueError("only a shadow revision may be promoted")
        from app.services.release_gate_evidence import REQUIRED_PROMOTION_GATES
        required = set(REQUIRED_PROMOTION_GATES)
        if not required.issubset({k for k, v in gate_evidence.items() if v == "PASS"}):
            raise ValueError("required promotion gates have not passed")
        runtime_manifest = dict(runtime_manifest or {})
        image_digest = str(runtime_manifest.get("image_digest") or "")
        model_manifest = runtime_manifest.get("model_manifest")
        prompt_hash = str(runtime_manifest.get("prompt_hash") or "")
        feature_flags = runtime_manifest.get("feature_flags")
        frontend_image_digest = str(runtime_manifest.get("frontend_image_digest") or "")
        deployment_manifest_id = str(runtime_manifest.get("deployment_manifest_id") or "")
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", image_digest):
            raise ValueError("runtime image digest is unavailable")
        if not isinstance(model_manifest, dict) or not model_manifest:
            raise ValueError("runtime model manifest is unavailable")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", prompt_hash):
            raise ValueError("runtime prompt hash is unavailable")
        if not isinstance(feature_flags, dict):
            raise ValueError("runtime feature flags are unavailable")
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", frontend_image_digest):
            raise ValueError("frontend image digest is unavailable")
        if not re.fullmatch(r"dm-[0-9a-fA-F]{24}", deployment_manifest_id):
            raise ValueError("deployment manifest id is unavailable")
        gate_artifacts = dict(gate_artifacts or {})
        if set(REQUIRED_PROMOTION_GATES) - set(gate_artifacts):
            raise ValueError("complete gate artifacts are unavailable")
        mismatched = [
            gate for gate in REQUIRED_PROMOTION_GATES
            if str((gate_artifacts.get(gate) or {}).get("image_digest") or "") != image_digest
        ]
        if mismatched:
            raise ValueError("gate artifacts do not match the release image: " + ", ".join(sorted(mismatched)))
        browser_artifact = gate_artifacts.get("KB-UX-01") or {}
        if (
            str(browser_artifact.get("frontend_image_digest") or "") != frontend_image_digest
            or str(browser_artifact.get("deployment_manifest_id") or "") != deployment_manifest_id
        ):
            raise ValueError("browser acceptance does not match the frontend image and deployment manifest")
        current = db.query(KnowledgeBaseRevision).filter(KnowledgeBaseRevision.kb_id == kb.id, KnowledgeBaseRevision.status == "active").all()
        for old in current:
            old.status = "retired"
        active_releases = db.query(KnowledgeRelease).filter(
            KnowledgeRelease.kb_id == kb.id,
            KnowledgeRelease.status == "active",
        ).all()
        for release in active_releases:
            release.status = "retired"
        runtime_ids = [release.runtime_release_id for release in active_releases if release.runtime_release_id]
        for runtime_release in db.query(RuntimeRelease).filter(RuntimeRelease.id.in_(runtime_ids)).all():
            runtime_release.status = "retired"
        revision.status = "active"; revision.activated_at = datetime.now(timezone.utc); kb.active_revision = revision.revision
        runtime_release = RuntimeRelease(
            tenant_id=kb.tenant_id,
            kb_revision_id=revision.id,
            image_digest=image_digest,
            frontend_image_digest=frontend_image_digest,
            deployment_manifest_id=deployment_manifest_id,
            model_manifest=model_manifest,
            prompt_hash=prompt_hash,
            feature_flags=feature_flags,
            rollout_percent=100,
            status="active",
        )
        db.add(runtime_release); db.flush()
        db.add(KnowledgeRelease(
            tenant_id=kb.tenant_id,
            kb_id=kb.id,
            kb_revision_id=revision.id,
            runtime_release_id=runtime_release.id,
            status="active",
        gate_evidence=dict(gate_evidence),
            activated_at=revision.activated_at,
        ))
        db.flush()
        # Phase H dual-write: the legacy KB revision remains the serving path,
        # while the exact same sealed membership is published to the canonical
        # KnowledgeUnit authority in this transaction.
        from app.services.knowledge_authority import publish_document_kb_revision

        publish_document_kb_revision(
            db,
            kb=kb,
            kb_revision=revision,
            created_by=created_by,
        )

    def rollback(self, db, *, kb: KnowledgeBase, target: KnowledgeBaseRevision, executed_by: Optional[UUID] = None) -> None:
        if target.status not in {"retired", "active"}:
            raise ValueError("rollback target must be a previously active revision")
        current_revision = db.query(KnowledgeBaseRevision).filter(
            KnowledgeBaseRevision.kb_id == kb.id,
            KnowledgeBaseRevision.status == "active",
        ).first()
        if current_revision is target:
            raise ValueError("target revision is already active")
        from_release = db.query(KnowledgeRelease).filter(
            KnowledgeRelease.kb_id == kb.id,
            KnowledgeRelease.status == "active",
        ).order_by(KnowledgeRelease.activated_at.desc()).first()
        to_release = db.query(KnowledgeRelease).filter(
            KnowledgeRelease.kb_id == kb.id,
            KnowledgeRelease.kb_revision_id == target.id,
        ).order_by(KnowledgeRelease.created_at.desc()).first()
        if from_release is None or to_release is None:
            raise ValueError("rollback audit evidence is unavailable")
        if not to_release.runtime_release_id:
            raise ValueError("rollback target runtime evidence is unavailable")
        to_runtime = db.query(RuntimeRelease).filter(RuntimeRelease.id == to_release.runtime_release_id).first()
        if to_runtime is None:
            raise ValueError("rollback target runtime release is unavailable")
        for rev in db.query(KnowledgeBaseRevision).filter(KnowledgeBaseRevision.kb_id == kb.id, KnowledgeBaseRevision.status == "active").all():
            rev.status = "retired"
        from_release.status = "rolled_back"
        to_release.status = "active"
        if from_release.runtime_release_id:
            from_runtime = db.query(RuntimeRelease).filter(RuntimeRelease.id == from_release.runtime_release_id).first()
            if from_runtime: from_runtime.status = "rolled_back"
        to_runtime.status = "active"; to_runtime.rollout_percent = 100
        target.status = "active"; target.activated_at = datetime.now(timezone.utc); to_release.activated_at = target.activated_at; kb.active_revision = target.revision
        db.add(RollbackPoint(
            tenant_id=kb.tenant_id,
            kb_id=kb.id,
            from_release_id=from_release.id,
            to_release_id=to_release.id,
            reason="manual rollback",
            executed_by=executed_by,
        ))
        db.flush()
