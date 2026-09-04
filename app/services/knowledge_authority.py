"""Versioned KnowledgeUnit projection and immutable release publication."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, DerivedArtifact, SourceAsset
from app.models.knowledge_unit import (
    KnowledgeUnitRecord,
    KnowledgeUnitRelease,
    KnowledgeUnitReleaseMembership,
    KnowledgeUnitRevision,
)

_TENANT_RELEASE_KEY = "tenant-default"


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _manifest_hash(revision_ids: list[UUID]) -> str:
    payload = "\n".join(sorted(str(item) for item in revision_ids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_unit_revision(
    db: Session,
    *,
    tenant_id: UUID,
    unit_key: str,
    unit_type: str,
    title: str,
    content: str,
    authority_class: str,
    acl_snapshot: dict[str, Any],
    source_resource_type: str,
    source_resource_id: str,
    created_by: UUID | None,
    source_asset_id: UUID | None = None,
    source_asset_revision_id: UUID | None = None,
    source_artifact_id: UUID | None = None,
    risk_level: str = "normal",
    applicability: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    policy_revision: int = 1,
) -> tuple[KnowledgeUnitRecord, KnowledgeUnitRevision]:
    normalized_key = str(unit_key or "").strip()
    normalized_content = str(content or "").strip()
    if not normalized_key or not normalized_content:
        raise ValueError("knowledge unit key and content are required")
    digest = _content_hash(normalized_content)
    unit = (
        db.query(KnowledgeUnitRecord)
        .filter(
            KnowledgeUnitRecord.tenant_id == tenant_id,
            KnowledgeUnitRecord.unit_key == normalized_key,
        )
        .with_for_update()
        .first()
    )
    if unit is None:
        unit = KnowledgeUnitRecord(
            tenant_id=tenant_id,
            unit_key=normalized_key,
            unit_type=unit_type,
            title=title,
            source_asset_id=source_asset_id,
            source_resource_type=source_resource_type,
            source_resource_id=source_resource_id,
            current_revision=0,
            status="active",
            metadata_json=dict(metadata or {}),
            created_by=created_by,
        )
        db.add(unit)
        db.flush()
    elif (
        unit.unit_type != unit_type
        or unit.source_resource_type != source_resource_type
        or unit.source_resource_id != source_resource_id
        or unit.source_asset_id != source_asset_id
    ):
        raise ValueError("knowledge unit identity conflicts with existing authority")

    revision = (
        db.query(KnowledgeUnitRevision)
        .filter(
            KnowledgeUnitRevision.tenant_id == tenant_id,
            KnowledgeUnitRevision.unit_id == unit.id,
            KnowledgeUnitRevision.content_hash == digest,
        )
        .order_by(KnowledgeUnitRevision.revision.desc())
        .first()
    )
    if revision is None:
        next_revision = int(unit.current_revision or 0) + 1
        revision = KnowledgeUnitRevision(
            tenant_id=tenant_id,
            unit_id=unit.id,
            revision=next_revision,
            content=normalized_content,
            content_hash=digest,
            authority_class=authority_class,
            quality_state="ready",
            risk_level=risk_level,
            acl_snapshot=dict(acl_snapshot or {}),
            applicability_json=dict(applicability or {}),
            metadata_json=dict(metadata or {}),
            source_asset_revision_id=source_asset_revision_id,
            source_artifact_id=source_artifact_id,
            policy_revision=policy_revision,
            effective_from=datetime.now(UTC),
            created_by=created_by,
        )
        db.add(revision)
        db.flush()
        unit.current_revision = next_revision
        unit.title = title
        unit.metadata_json = dict(metadata or {})
    return unit, revision


def _activate_release(
    db: Session,
    *,
    tenant_id: UUID,
    release_key: str,
    revision_acl_pairs: Iterable[tuple[KnowledgeUnitRevision, dict[str, Any]]],
    created_by: UUID | None,
    policy_revision: int,
    gate_evidence: dict[str, Any] | None,
    scope_kind: str = "tenant",
    scope_id: UUID | None = None,
    scope_revision_id: UUID | None = None,
) -> tuple[KnowledgeUnitRelease, dict[UUID, KnowledgeUnitReleaseMembership], bool]:
    pairs = list(revision_acl_pairs)
    revision_ids = [revision.id for revision, _acl in pairs]
    manifest_hash = _manifest_hash(revision_ids)
    active_release = (
        db.query(KnowledgeUnitRelease)
        .filter(
            KnowledgeUnitRelease.tenant_id == tenant_id,
            KnowledgeUnitRelease.release_key == release_key,
            KnowledgeUnitRelease.status == "active",
        )
        .with_for_update()
        .first()
    )
    if active_release is not None and active_release.manifest_hash == manifest_hash:
        memberships = {
            membership.unit_revision_id: membership
            for membership in db.query(KnowledgeUnitReleaseMembership).filter(
                KnowledgeUnitReleaseMembership.tenant_id == tenant_id,
                KnowledgeUnitReleaseMembership.release_id == active_release.id,
                KnowledgeUnitReleaseMembership.status == "active",
            )
        }
        return active_release, memberships, True

    release_revision = (
        int(
            db.query(func.max(KnowledgeUnitRelease.revision))
            .filter(
                KnowledgeUnitRelease.tenant_id == tenant_id,
                KnowledgeUnitRelease.release_key == release_key,
            )
            .scalar()
            or 0
        )
        + 1
    )
    release = KnowledgeUnitRelease(
        tenant_id=tenant_id,
        release_key=release_key,
        revision=release_revision,
        scope_kind=scope_kind,
        scope_id=scope_id,
        scope_revision_id=scope_revision_id,
        status="candidate",
        policy_revision=policy_revision,
        manifest_hash=manifest_hash,
        gate_evidence={"publisher": "knowledge_authority", **dict(gate_evidence or {})},
        created_by=created_by,
    )
    db.add(release)
    db.flush()
    memberships: dict[UUID, KnowledgeUnitReleaseMembership] = {}
    for revision, acl_snapshot in pairs:
        membership = KnowledgeUnitReleaseMembership(
            tenant_id=tenant_id,
            release_id=release.id,
            unit_revision_id=revision.id,
            acl_snapshot=dict(acl_snapshot or {}),
            policy_revision=policy_revision,
            status="active",
            added_by=created_by,
        )
        db.add(membership)
        memberships[revision.id] = membership
    if active_release is not None:
        active_release.status = "retired"
        db.flush()
    release.status = "active"
    release.activated_at = datetime.now(UTC)
    db.flush()
    return release, memberships, False


def publish_knowledge_unit(
    db: Session,
    *,
    tenant_id: UUID,
    unit_key: str,
    unit_type: str,
    title: str,
    content: str,
    authority_class: str,
    acl_snapshot: dict[str, Any],
    source_resource_type: str,
    source_resource_id: str,
    created_by: UUID | None,
    source_asset_id: UUID | None = None,
    source_asset_revision_id: UUID | None = None,
    source_artifact_id: UUID | None = None,
    risk_level: str = "normal",
    applicability: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    policy_revision: int = 1,
    gate_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotently publish one immutable revision into a new release image."""
    unit, revision = _ensure_unit_revision(
        db,
        tenant_id=tenant_id,
        unit_key=unit_key,
        unit_type=unit_type,
        title=title,
        content=content,
        authority_class=authority_class,
        acl_snapshot=acl_snapshot,
        source_resource_type=source_resource_type,
        source_resource_id=source_resource_id,
        created_by=created_by,
        source_asset_id=source_asset_id,
        source_asset_revision_id=source_asset_revision_id,
        source_artifact_id=source_artifact_id,
        risk_level=risk_level,
        applicability=applicability,
        metadata=metadata,
        policy_revision=policy_revision,
    )

    active_release = (
        db.query(KnowledgeUnitRelease)
        .filter(
            KnowledgeUnitRelease.tenant_id == tenant_id,
            KnowledgeUnitRelease.release_key == _TENANT_RELEASE_KEY,
            KnowledgeUnitRelease.status == "active",
        )
        .with_for_update()
        .first()
    )
    prior_memberships: list[KnowledgeUnitReleaseMembership] = []
    if active_release is not None:
        prior_memberships = (
            db.query(KnowledgeUnitReleaseMembership)
            .join(
                KnowledgeUnitRevision,
                (
                    KnowledgeUnitRevision.tenant_id
                    == KnowledgeUnitReleaseMembership.tenant_id
                )
                & (
                    KnowledgeUnitRevision.id
                    == KnowledgeUnitReleaseMembership.unit_revision_id
                ),
            )
            .filter(
                KnowledgeUnitReleaseMembership.tenant_id == tenant_id,
                KnowledgeUnitReleaseMembership.release_id == active_release.id,
                KnowledgeUnitReleaseMembership.status == "active",
                KnowledgeUnitRevision.unit_id != unit.id,
            )
            .all()
        )

    revision_acl_pairs: list[tuple[KnowledgeUnitRevision, dict[str, Any]]] = []
    for prior in prior_memberships:
        prior_revision = (
            db.query(KnowledgeUnitRevision)
            .filter(
                KnowledgeUnitRevision.tenant_id == tenant_id,
                KnowledgeUnitRevision.id == prior.unit_revision_id,
            )
            .one()
        )
        revision_acl_pairs.append((prior_revision, dict(prior.acl_snapshot or {})))
    revision_acl_pairs.append((revision, dict(acl_snapshot or {})))
    release, memberships, idempotent = _activate_release(
        db,
        tenant_id=tenant_id,
        release_key=_TENANT_RELEASE_KEY,
        revision_acl_pairs=revision_acl_pairs,
        created_by=created_by,
        policy_revision=policy_revision,
        gate_evidence=gate_evidence,
    )
    membership = memberships[revision.id]
    entity_projection = {
        "resolved_count": 0,
        "ambiguous_count": 0,
        "unresolved_count": 0,
    }
    from app.config import settings

    from app.services.media_feature_flags import media_capability_enabled_for

    if applicability and media_capability_enabled_for(
        tenant_id, capability_enabled=settings.ENTITY_LINKING_V1
    ):
        from app.services.entity_knowledge_links import (
            project_unit_entities_from_values,
        )

        entity_values = [
            str(value)
            for key in (
                "entity_ids",
                "equipment_ids",
                "product_ids",
                "customer_ids",
                "process_ids",
                "site_ids",
            )
            for value in (applicability.get(key) or [])
            if str(value or "").strip()
        ]
        entity_projection = project_unit_entities_from_values(
            db,
            tenant_id=tenant_id,
            unit_revision_id=revision.id,
            values=entity_values,
        )
    return {
        "unit_id": str(unit.id),
        "unit_revision_id": str(revision.id),
        "release_id": str(release.id),
        "membership_id": str(membership.id),
        "idempotent": idempotent,
        "entity_projection": entity_projection,
    }


def publish_approved_video_procedure(
    db: Session,
    *,
    asset: SourceAsset,
    asset_revision: AssetRevision,
    artifact: DerivedArtifact,
    published_procedure: dict[str, Any],
    reviewer_id: UUID,
    high_risk: bool,
) -> dict[str, Any]:
    content = json.dumps(published_procedure, ensure_ascii=False, sort_keys=True)
    return publish_knowledge_unit(
        db,
        tenant_id=asset.tenant_id,
        unit_key=f"video-procedure:{artifact.id}",
        unit_type="procedure",
        title=str(published_procedure.get("title") or asset.title),
        content=content,
        authority_class="reviewed_video_procedure",
        acl_snapshot=dict(asset.acl_reference or {}),
        source_resource_type="derived_artifact",
        source_resource_id=str(artifact.id),
        source_asset_id=asset.id,
        source_asset_revision_id=asset_revision.id,
        source_artifact_id=artifact.id,
        risk_level="high" if high_risk else "normal",
        applicability={
            "equipment_ids": list(
                published_procedure.get("applicable_equipment") or []
            ),
            "role_ids": list(published_procedure.get("applicable_roles") or []),
        },
        metadata={
            "deep_link": f"/knowledge/videos/{asset.id}",
            "governance_state": published_procedure.get("governance_state"),
        },
        created_by=reviewer_id,
        gate_evidence={
            "reviewer_id": str(reviewer_id),
            "artifact_id": str(artifact.id),
            "decision": "approved",
        },
    )


def publish_approved_knowhow(
    db: Session,
    *,
    card: Any,
    reviewer_id: UUID,
) -> dict[str, Any]:
    """Project an approved legacy know-how card into tenant release authority."""
    from app.services.asset_visibility import canonical_asset_acl

    payload = {
        "title": card.title,
        "summary": card.summary or "",
        "steps": list(card.steps or []),
        "recommended_actions": list(card.recommended_actions or []),
        "prerequisites": list(card.prerequisites or []),
        "cautions": list(card.cautions or []),
        "risks": list(card.risks or []),
        "prohibited_actions": list(card.prohibited_actions or []),
        "source_quotes": list(card.source_quotes or []),
        "related_sop_ids": list(card.related_sop_ids or []),
    }
    acl = canonical_asset_acl(owner_subject_id=card.owner_id, visibility="tenant")
    return publish_knowledge_unit(
        db,
        tenant_id=card.tenant_id,
        unit_key=f"knowhow:{card.id}",
        unit_type="knowhow",
        title=card.title,
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        authority_class="reviewed_knowhow",
        acl_snapshot=acl,
        source_resource_type="knowhow_card",
        source_resource_id=str(card.id),
        created_by=reviewer_id,
        risk_level="high" if card.risk_level == "high" else "normal",
        applicability={
            "role_ids": list(card.applicable_roles or []),
            "equipment_ids": list(card.equipment_ids or []),
            "product_ids": list(card.product_ids or []),
            "customer_ids": list(card.customer_ids or []),
        },
        metadata={
            "legacy_card_id": card.card_id,
            "module_key": "training_knowhow",
            "authority_level": int(card.authority_level or 60),
            "source_type": card.source_type,
            "source_document_id": card.source_document_id,
            "deep_link": f"/knowhow/{card.id}",
        },
        gate_evidence={
            "reviewer_id": str(reviewer_id),
            "decision": "approved",
            "legacy_version": int(card.version or 1),
        },
    )


def retire_knowledge_unit(
    db: Session,
    *,
    tenant_id: UUID,
    unit_key: str,
    retired_by: UUID | None,
) -> dict[str, Any]:
    """Tombstone a unit and atomically publish a release without it."""
    unit = (
        db.query(KnowledgeUnitRecord)
        .filter(
            KnowledgeUnitRecord.tenant_id == tenant_id,
            KnowledgeUnitRecord.unit_key == unit_key,
        )
        .with_for_update()
        .first()
    )
    if unit is None or unit.status == "tombstoned":
        return {"unit_key": unit_key, "idempotent": True}
    active_release = (
        db.query(KnowledgeUnitRelease)
        .filter(
            KnowledgeUnitRelease.tenant_id == tenant_id,
            KnowledgeUnitRelease.release_key == _TENANT_RELEASE_KEY,
            KnowledgeUnitRelease.status == "active",
        )
        .with_for_update()
        .first()
    )
    retained: list[tuple[KnowledgeUnitRevision, dict[str, Any]]] = []
    if active_release is not None:
        rows = (
            db.query(KnowledgeUnitRevision, KnowledgeUnitReleaseMembership)
            .join(
                KnowledgeUnitReleaseMembership,
                (
                    KnowledgeUnitReleaseMembership.tenant_id
                    == KnowledgeUnitRevision.tenant_id
                )
                & (
                    KnowledgeUnitReleaseMembership.unit_revision_id
                    == KnowledgeUnitRevision.id
                ),
            )
            .filter(
                KnowledgeUnitReleaseMembership.tenant_id == tenant_id,
                KnowledgeUnitReleaseMembership.release_id == active_release.id,
                KnowledgeUnitReleaseMembership.status == "active",
                KnowledgeUnitRevision.unit_id != unit.id,
            )
            .all()
        )
        retained = [
            (revision, dict(membership.acl_snapshot or {}))
            for revision, membership in rows
        ]
    unit.status = "tombstoned"
    unit.tombstoned_at = datetime.now(UTC)
    release, _memberships, _idempotent = _activate_release(
        db,
        tenant_id=tenant_id,
        release_key=_TENANT_RELEASE_KEY,
        revision_acl_pairs=retained,
        created_by=retired_by,
        policy_revision=1,
        gate_evidence={"retired_unit_id": str(unit.id)},
    )
    return {
        "unit_id": str(unit.id),
        "release_id": str(release.id),
        "idempotent": False,
    }


def publish_document_kb_revision(
    db: Session,
    *,
    kb: Any,
    kb_revision: Any,
    created_by: UUID | None,
) -> dict[str, Any]:
    """Publish exactly the chunks sealed into one active legacy KB revision."""
    from app.models.asset import AssetRevision, SourceAsset
    from app.models.document import Document, DocumentChunk
    from app.models.knowledge_engine import KnowledgeBaseRevisionDocument
    from app.services.asset_visibility import canonical_asset_acl

    members = (
        db.query(KnowledgeBaseRevisionDocument)
        .filter(
            KnowledgeBaseRevisionDocument.tenant_id == kb.tenant_id,
            KnowledgeBaseRevisionDocument.kb_revision_id == kb_revision.id,
        )
        .order_by(KnowledgeBaseRevisionDocument.document_id)
        .all()
    )
    revision_acl_pairs: list[tuple[KnowledgeUnitRevision, dict[str, Any]]] = []
    for member in members:
        document = (
            db.query(Document)
            .filter(
                Document.tenant_id == kb.tenant_id,
                Document.id == member.document_id,
                Document.tombstoned_at.is_(None),
            )
            .one()
        )
        asset = None
        asset_revision = None
        if document.source_asset_id:
            asset = (
                db.query(SourceAsset)
                .filter(
                    SourceAsset.tenant_id == kb.tenant_id,
                    SourceAsset.id == document.source_asset_id,
                    SourceAsset.tombstoned_at.is_(None),
                )
                .first()
            )
            if asset is not None:
                asset_revision = (
                    db.query(AssetRevision)
                    .filter(
                        AssetRevision.tenant_id == kb.tenant_id,
                        AssetRevision.asset_id == asset.id,
                        AssetRevision.revision == member.document_revision,
                    )
                    .first()
                )
        acl = dict(member.acl_snapshot or {})
        if not acl and asset is not None:
            acl = dict(asset.acl_reference or {})
        if not acl:
            acl = canonical_asset_acl(
                owner_subject_id=document.uploaded_by,
                visibility="restricted" if document.department_id else "tenant",
                allowed_department_ids=(
                    [document.department_id] if document.department_id else []
                ),
            )
        chunks = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.tenant_id == kb.tenant_id,
                DocumentChunk.document_id == document.id,
                DocumentChunk.document_revision == member.document_revision,
            )
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        for chunk in chunks:
            _unit, unit_revision = _ensure_unit_revision(
                db,
                tenant_id=kb.tenant_id,
                unit_key=f"document:{document.id}:chunk:{chunk.chunk_index}",
                unit_type="narrative",
                title=f"{document.filename} · {chunk.chunk_index + 1}",
                content=chunk.text,
                authority_class="primary_document",
                acl_snapshot=acl,
                source_resource_type="document_chunk",
                source_resource_id=str(chunk.id),
                created_by=created_by,
                source_asset_id=asset.id if asset else None,
                source_asset_revision_id=asset_revision.id if asset_revision else None,
                applicability={"knowledge_base_id": str(kb.id)},
                metadata={
                    "document_id": str(document.id),
                    "document_revision": member.document_revision,
                    "chunk_id": str(chunk.id),
                    "chunk_index": chunk.chunk_index,
                    "locator": dict(chunk.metadata_json or {}),
                },
                policy_revision=int(member.policy_revision or 1),
            )
            revision_acl_pairs.append((unit_revision, acl))
    release, memberships, idempotent = _activate_release(
        db,
        tenant_id=kb.tenant_id,
        release_key=f"knowledge-base:{kb.id}",
        revision_acl_pairs=revision_acl_pairs,
        created_by=created_by,
        policy_revision=int(kb_revision.policy_revision or 1),
        gate_evidence={
            "legacy_kb_revision_id": str(kb_revision.id),
            "legacy_manifest_hash": kb_revision.manifest_hash,
        },
        scope_kind="knowledge_base",
        scope_id=kb.id,
        scope_revision_id=kb_revision.id,
    )
    return {
        "release_id": str(release.id),
        "release_revision": release.revision,
        "unit_count": len(memberships),
        "idempotent": idempotent,
    }
