"""Isolated-staging knowledge publication for the P5 capacity workload.

This is test-data setup, not a production knowledge release.  It intentionally
does not manufacture promotion-gate evidence or create a ``KnowledgeRelease``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy.orm import Session

from app.config import settings
from app.models.document import Document, DocumentChunk
from app.models.kb_maintenance import DocumentVersion
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.services.kb_revision_runtime import KBRevisionRuntime, canonical_hash

_MARKER_PATTERN = re.compile(r"P5-[A-Z0-9-]{8,80}")
_KB_NAME = "P5 Isolated Staging Capacity Fixture"


def activate_staging_capacity_fixture(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    marker: str,
    confirm_isolated_staging: bool,
) -> KnowledgeBaseRevision:
    """Publish exactly one synthetic fixture into a staging-only active scope.

    The formal candidate/shadow/promotion path remains mandatory everywhere
    else.  This helper exists so a capacity test can exercise real reader
    semantics without claiming that synthetic load data passed release gates.
    """
    if settings.APP_ENV.lower() != "staging":
        raise RuntimeError("P5 capacity fixture activation requires APP_ENV=staging")
    if not confirm_isolated_staging:
        raise RuntimeError("isolated staging confirmation is required")
    if not _MARKER_PATTERN.fullmatch(marker):
        raise ValueError("invalid P5 fixture marker")

    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
            Document.tombstoned_at.is_(None),
        )
        .one_or_none()
    )
    if document is None:
        raise ValueError("P5 fixture document does not belong to the tenant")
    if document.status != "completed":
        raise ValueError("P5 fixture document is not completed")

    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document.id,
            DocumentChunk.document_revision == int(document.version or 1),
        )
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    snapshot = "\n".join(chunk.text or "" for chunk in chunks)
    if marker not in snapshot:
        raise ValueError("P5 fixture marker is absent from processed chunks")

    kb_id = uuid5(tenant_id, "p5-isolated-staging-capacity-fixture")
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).one_or_none()
    if kb is None:
        kb = KnowledgeBase(
            id=kb_id,
            tenant_id=tenant_id,
            name=_KB_NAME,
            description="Synthetic capacity fixture; never a production release",
            status="active",
            active_revision=0,
        )
        db.add(kb)
        db.flush()
    elif kb.tenant_id != tenant_id:
        raise ValueError("P5 fixture knowledge base tenant mismatch")

    document.knowledge_base_id = kb.id
    version_number = int(document.version or 1)
    version = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.document_id == document.id,
            DocumentVersion.version == version_number,
        )
        .order_by(DocumentVersion.created_at.desc())
        .first()
    )
    if version is None:
        version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=document.id,
            version=version_number,
            filename=document.filename,
            file_path=document.file_path,
            file_size=document.file_size,
            file_type=document.file_type,
            chunk_count=len(chunks),
            status="completed",
            quality_report=document.quality_report,
            uploaded_by=document.uploaded_by,
            change_note="P5 isolated staging capacity fixture",
            content_snapshot=snapshot,
        )
        db.add(version)
        db.flush()
    elif marker not in (version.content_snapshot or ""):
        raise ValueError("existing document version does not contain the P5 marker")

    runtime = KBRevisionRuntime()
    revision = runtime.create_candidate(
        db,
        kb=kb,
        document_versions=[version],
        manifest_versions={"fixture_schema": "p5-staging-capacity-v1"},
    )
    manifest = dict(revision.manifest_json or {})
    manifest.update(
        {
            "execution_class": "isolated_staging_fixture",
            "formal_release": False,
            "marker": marker,
        }
    )
    revision.manifest_json = manifest
    revision.manifest_hash = canonical_hash(manifest)
    revision.change_summary = "P5 synthetic isolated-staging capacity fixture"
    runtime.transition(revision, "shadow")

    for active in (
        db.query(KnowledgeBaseRevision)
        .filter(
            KnowledgeBaseRevision.kb_id == kb.id,
            KnowledgeBaseRevision.status == "active",
            KnowledgeBaseRevision.id != revision.id,
        )
        .all()
    ):
        active.status = "retired"
    # Deliberate staging-only activation.  Do not call ``promote`` because that
    # would falsely represent synthetic capacity data as a gated release.
    revision.status = "active"
    revision.activated_at = datetime.now(UTC)
    kb.active_revision = revision.revision
    db.flush()
    return revision
