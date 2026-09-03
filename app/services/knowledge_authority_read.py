"""Fail-closed reads and parity reports for active KnowledgeUnit releases."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models.asset import AssetRevision, DerivedArtifact, EvidenceSpan, SourceAsset
from app.models.knowledge_unit import (
    KnowledgeUnitRecord,
    KnowledgeUnitRelease,
    KnowledgeUnitReleaseMembership,
    KnowledgeUnitRevision,
)
from app.platform.assets.access import AssetAccessPolicy
from app.services.asset_visibility import asset_access_allows

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActiveKnowledgeUnit:
    unit_id: UUID
    unit_revision_id: UUID
    release_id: UUID
    unit_key: str
    unit_type: str
    title: str
    content: str
    source_resource_type: str
    source_resource_id: str
    source_asset_id: UUID | None
    source_asset_revision_id: UUID | None
    source_artifact_id: UUID | None
    metadata: dict[str, Any]


def list_active_knowledge_units(
    db: Session,
    *,
    authz: AuthorizationContext,
    kb_revision_ids: Iterable[UUID] | None = None,
    unit_types: Iterable[str] | None = None,
    query_text: str | None = None,
) -> list[ActiveKnowledgeUnit]:
    """Read only active, visible memberships from the canonical authority.

    Explicit KB revision scope is strict: tenant-default know-how/video units
    are not silently merged into a scoped query.
    """
    explicit_scope = kb_revision_ids is not None
    requested_revisions = tuple(kb_revision_ids or ())
    query = (
        db.query(
            KnowledgeUnitRecord,
            KnowledgeUnitRevision,
            KnowledgeUnitRelease,
            KnowledgeUnitReleaseMembership,
        )
        .join(
            KnowledgeUnitRevision,
            (KnowledgeUnitRevision.tenant_id == KnowledgeUnitRecord.tenant_id)
            & (KnowledgeUnitRevision.unit_id == KnowledgeUnitRecord.id),
        )
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
        .join(
            KnowledgeUnitRelease,
            (KnowledgeUnitRelease.tenant_id == KnowledgeUnitReleaseMembership.tenant_id)
            & (KnowledgeUnitRelease.id == KnowledgeUnitReleaseMembership.release_id),
        )
        .filter(
            KnowledgeUnitRecord.tenant_id == authz.tenant_id,
            KnowledgeUnitRecord.status == "active",
            KnowledgeUnitRevision.quality_state == "ready",
            KnowledgeUnitRelease.status == "active",
            KnowledgeUnitReleaseMembership.status == "active",
        )
    )
    if explicit_scope:
        if not requested_revisions:
            return []
        query = query.filter(
            KnowledgeUnitRelease.scope_kind == "knowledge_base",
            KnowledgeUnitRelease.scope_revision_id.in_(requested_revisions),
        )
    normalized_types = tuple(str(item) for item in (unit_types or ()) if item)
    if normalized_types:
        query = query.filter(KnowledgeUnitRecord.unit_type.in_(normalized_types))

    visible: list[ActiveKnowledgeUnit] = []
    seen_revision_ids: set[UUID] = set()
    for unit, revision, release, membership in query.all():
        if revision.id in seen_revision_ids:
            continue
        try:
            if unit.source_asset_id:
                asset = (
                    db.query(SourceAsset)
                    .filter(
                        SourceAsset.tenant_id == authz.tenant_id,
                        SourceAsset.id == unit.source_asset_id,
                    )
                    .first()
                )
                if asset is None or not asset_access_allows(db, asset, authz=authz):
                    continue
                if revision.source_asset_revision_id is None:
                    continue
                source_revision = (
                    db.query(AssetRevision)
                    .filter(
                        AssetRevision.tenant_id == authz.tenant_id,
                        AssetRevision.id == revision.source_asset_revision_id,
                        AssetRevision.asset_id == unit.source_asset_id,
                        AssetRevision.ingestion_status == "ready",
                    )
                    .first()
                )
                if source_revision is None:
                    continue
                if revision.source_artifact_id:
                    source_artifact = (
                        db.query(DerivedArtifact)
                        .filter(
                            DerivedArtifact.tenant_id == authz.tenant_id,
                            DerivedArtifact.id == revision.source_artifact_id,
                            DerivedArtifact.asset_revision_id
                            == revision.source_asset_revision_id,
                            DerivedArtifact.quality_state == "ready",
                        )
                        .first()
                    )
                    if source_artifact is None:
                        continue
                if unit.source_resource_type == "evidence_span":
                    try:
                        evidence_span_id = UUID(str(unit.source_resource_id))
                    except (TypeError, ValueError, AttributeError):
                        continue
                    span = (
                        db.query(EvidenceSpan.id)
                        .filter(
                            EvidenceSpan.tenant_id == authz.tenant_id,
                            EvidenceSpan.id == evidence_span_id,
                            EvidenceSpan.artifact_id == revision.source_artifact_id,
                            EvidenceSpan.asset_revision_id
                            == revision.source_asset_revision_id,
                        )
                        .first()
                    )
                    if span is None:
                        continue
            else:
                if (
                    revision.source_asset_revision_id is not None
                    or revision.source_artifact_id is not None
                ):
                    continue
                if unit.source_resource_type == "document_chunk":
                    from app.models.document import Document

                    document_id = (revision.metadata_json or {}).get("document_id")
                    try:
                        parsed_document_id = UUID(str(document_id))
                    except (TypeError, ValueError, AttributeError):
                        continue
                    document = (
                        db.query(Document.id)
                        .filter(
                            Document.tenant_id == authz.tenant_id,
                            Document.id == parsed_document_id,
                            Document.tombstoned_at.is_(None),
                        )
                        .first()
                    )
                    if document is None:
                        continue
                if not AssetAccessPolicy.from_mapping(
                    membership.acl_snapshot or revision.acl_snapshot
                ).allows(authz):
                    continue
        except Exception:
            logger.exception("knowledge unit ACL failed closed: %s", unit.id)
            continue
        if not _applicability_allows(
            db,
            authz=authz,
            revision=revision,
            unit=unit,
            query_text=query_text,
        ):
            continue
        visible.append(
            ActiveKnowledgeUnit(
                unit_id=unit.id,
                unit_revision_id=revision.id,
                release_id=release.id,
                unit_key=unit.unit_key,
                unit_type=unit.unit_type,
                title=unit.title,
                content=revision.content,
                source_resource_type=unit.source_resource_type,
                source_resource_id=unit.source_resource_id,
                source_asset_id=unit.source_asset_id,
                source_asset_revision_id=revision.source_asset_revision_id,
                source_artifact_id=revision.source_artifact_id,
                metadata=dict(revision.metadata_json or {}),
            )
        )
        seen_revision_ids.add(revision.id)
    return visible


def _applicability_allows(
    db: Session,
    *,
    authz: AuthorizationContext,
    revision: KnowledgeUnitRevision,
    unit: KnowledgeUnitRecord,
    query_text: str | None,
) -> bool:
    applicability = dict(revision.applicability_json or {})
    required_roles = {
        str(item).casefold() for item in applicability.get("role_ids") or []
    }
    caller_roles = {str(item).casefold() for item in authz.role_ids or ()}
    if required_roles and not caller_roles.intersection(required_roles):
        return False
    if query_text is not None:
        query_key = str(query_text).casefold().replace(" ", "")
        for field in ("equipment_ids", "product_ids", "customer_ids"):
            values = [
                str(item).casefold().replace(" ", "")
                for item in applicability.get(field) or []
                if item
            ]
            if values and not any(value in query_key for value in values):
                return False
        authority_level = int(
            (revision.metadata_json or {}).get("authority_level") or 0
        )
        safety_query = any(
            token in query_key for token in ("工安", "安全", "危險", "停機", "品質放行")
        )
        if (
            revision.risk_level in {"high", "critical"} or safety_query
        ) and authority_level < 90:
            return False
    module_key = str((revision.metadata_json or {}).get("module_key") or "")
    if module_key:
        from app.platform.knowledge import is_core_query_mode

        if not is_core_query_mode(module_key):
            from app.composition.application_entitlements import (
                is_application_module_enabled,
            )

            if not is_application_module_enabled(
                db=db,
                tenant_id=authz.tenant_id,
                module_key=module_key,
            ):
                return False
    return unit.status == "active"


def sealed_parity_report(
    *,
    legacy_resource_ids: Iterable[str],
    authority_units: Iterable[ActiveKnowledgeUnit],
) -> dict[str, Any]:
    legacy = {str(item) for item in legacy_resource_ids}
    authority = {item.source_resource_id for item in authority_units}
    return {
        "status": "match" if legacy == authority else "mismatch",
        "legacy_count": len(legacy),
        "authority_count": len(authority),
        "missing_from_authority": sorted(legacy - authority),
        "unexpected_in_authority": sorted(authority - legacy),
    }
