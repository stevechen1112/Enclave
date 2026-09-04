"""Source-neutral review workspace read model and decision guardrails."""

from __future__ import annotations

import importlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.agent.review_queue import ReviewQueueManager
from app.composition.packs import build_pack_registry
from app.core.authorization import AuthorizationContext
from app.models.asset import (
    ArtifactReviewDecision,
    AssetRevision,
    DerivedArtifact,
    EvidenceSpan,
    SourceAsset,
)
from app.models.audit import AuditLog
from app.models.ingestion import IngestionJob
from app.models.review_item import ReviewItem as LegacyReviewItem
from app.models.user import User
from app.platform.assets import AssetAccessPolicy
from app.platform.packs import PackTenantContext
from app.services.asset_visibility import asset_access_allows

_LOW_CONFIDENCE = 0.8
_HIGH_RISK_KINDS = {"procedure_candidate", "sop_conflict_report"}
_BATCH_KINDS = {"extracted_text", "ocr_region", "table", "transcript_segment"}
_NON_ACTIONABLE_KINDS = {
    "speaker_turn",
    "video_scene",
    "timeline_alignment",
    "sop_conflict_report",
    "media_probe",
    "audio_quality_profile",
    "audio_working_copy",
    "transcript_raw",
    "video_keyframe_candidate",
    "ocr_track",
    "visual_observation",
    "audio_signal_outlier",
    "multimodal_segment_summary",
}
logger = logging.getLogger(__name__)


def _knowledge_unit_type(artifact_kind: str) -> str:
    if artifact_kind == "table":
        return "row"
    if artifact_kind == "entity_candidate":
        return "entity"
    return "narrative"


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _load(path: str) -> Any:
    module_name, attribute = path.split(":", 1)
    return getattr(importlib.import_module(module_name), attribute)


def _policy_expired(metadata: dict[str, Any]) -> bool:
    raw = metadata.get("review_policy_expires_at")
    if not raw:
        return False
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed <= datetime.now(UTC)
    except (TypeError, ValueError):
        return True


def _artifact_risk(artifact: DerivedArtifact) -> str:
    metadata = dict(artifact.metadata_json or {})
    if artifact.artifact_kind in _HIGH_RISK_KINDS or metadata.get("high_risk"):
        return "high"
    if artifact.artifact_kind in {"equipment_state", "action_event"}:
        return "medium"
    return "low"


def _artifact_conflicts(content: str | None) -> list[dict[str, Any]]:
    try:
        payload = json.loads(content or "{}")
    except (json.JSONDecodeError, TypeError):
        return []
    conflicts = payload.get("conflicts") if isinstance(payload, dict) else None
    return [row for row in (conflicts or []) if isinstance(row, dict)]


def _locator_dict(span: EvidenceSpan, asset: SourceAsset) -> dict[str, Any]:
    query: list[tuple[str, str | int]] = [("evidence", str(span.id))]
    if span.start_ms is not None:
        query.append(("t", int(span.start_ms)))
    if span.end_ms is not None:
        query.append(("end", int(span.end_ms)))
    if span.page is not None:
        query.append(("page", int(span.page)))
    if span.section:
        query.append(("section", span.section))
    if span.frame_index is not None:
        query.append(("frame", span.frame_index))
    if span.bbox:
        bbox = span.bbox
        if isinstance(bbox, dict):
            bbox = [bbox.get(key, 0) for key in ("x", "y", "w", "h")]
        query.append(("bbox", ",".join(str(value) for value in bbox)))
    base = (
        f"/knowledge/videos/{asset.id}"
        if asset.asset_kind == "video"
        else f"/knowledge/assets/{asset.id}"
    )
    return {
        "id": str(span.id),
        "kind": span.locator_kind,
        "page": span.page,
        "section": span.section,
        "paragraph_index": span.paragraph_index,
        "slide_number": span.slide_number,
        "bbox": span.bbox,
        "coordinate_space": span.coordinate_space,
        "locator_fallback": span.locator_fallback,
        "worksheet": span.worksheet,
        "table_name": span.table_name,
        "row_number": span.row_number,
        "column_name": span.column_name,
        "cell_range": span.cell_range,
        "start_ms": span.start_ms,
        "end_ms": span.end_ms,
        "speaker": span.speaker,
        "frame_index": span.frame_index,
        "source_system": span.source_system,
        "source_record_id": span.source_record_id,
        "field_path": span.field_path,
        "deep_link": f"{base}?{urlencode(query)}",
    }


def _blocked_reasons(
    artifact: DerivedArtifact,
    asset: SourceAsset,
    *,
    current_user: User,
    linked_conflicts: list[dict[str, Any]] | None = None,
    evidence_count: int | None = None,
) -> list[str]:
    metadata = dict(artifact.metadata_json or {})
    blocked: list[str] = []
    if not isinstance(asset.acl_reference, dict) or not asset.acl_reference.get(
        "policy_revision"
    ):
        blocked.append("acl_policy_missing")
    else:
        try:
            AssetAccessPolicy.from_mapping(asset.acl_reference)
        except (TypeError, ValueError):
            blocked.append("acl_policy_invalid")
    if _policy_expired(metadata):
        blocked.append("review_policy_expired")
    # Separation of duty protects inferred decisions and high-risk operating
    # guidance.  It must not make a two-person tenant unable to confirm the
    # literal OCR/transcript extracted from a source they uploaded.
    if asset.created_by == current_user.id and (
        _artifact_risk(artifact) != "low" or artifact.artifact_kind not in _BATCH_KINDS
    ):
        blocked.append("separation_of_duty")
    if evidence_count == 0:
        blocked.append("evidence_missing")
    conflicts = (
        linked_conflicts
        if linked_conflicts is not None
        else _artifact_conflicts(artifact.content)
    )
    if any(not row.get("resolved") for row in conflicts):
        blocked.append("unresolved_sop_conflicts")
    return blocked


def _artifact_item(
    artifact: DerivedArtifact,
    revision: AssetRevision,
    asset: SourceAsset,
    spans: list[EvidenceSpan],
    *,
    current_user: User,
    linked_conflicts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata = dict(artifact.metadata_json or {})
    risk = _artifact_risk(artifact)
    blocked = _blocked_reasons(
        artifact,
        asset,
        current_user=current_user,
        linked_conflicts=linked_conflicts,
        evidence_count=len(spans),
    )
    try:
        parsed_content: Any = json.loads(artifact.content or "")
    except (json.JSONDecodeError, TypeError):
        parsed_content = artifact.content
    try:
        department_ids = list(
            AssetAccessPolicy.from_mapping(
                asset.acl_reference or {}
            ).allowed_department_ids
        )
    except (TypeError, ValueError):
        department_ids = []
    evidence = [_locator_dict(span, asset) for span in spans]
    for index, conflict in enumerate(linked_conflicts or []):
        source = conflict.get("sop_evidence")
        if not isinstance(source, dict) or not source.get("document_id"):
            continue
        page = source.get("page")
        suffix = f"?page={page}" if page else ""
        evidence.append(
            {
                "id": f"sop:{source['document_id']}:{index}",
                "kind": "document",
                "page": page,
                "section": source.get("title") or "正式 SOP",
                "deep_link": f"/knowledge/documents/{source['document_id']}{suffix}",
            }
        )
    return {
        "id": f"artifact:{artifact.id}",
        "source_group_key": f"asset:{asset.id}",
        "source_asset_id": str(asset.id),
        "provider": "core.asset_artifact",
        "source_type": artifact.artifact_kind,
        "asset_kind": asset.asset_kind,
        "title": asset.title,
        "subtitle": metadata.get("label") or artifact.artifact_kind,
        "status": "pending",
        "risk_level": risk,
        "confidence": artifact.confidence,
        "created_at": _iso(artifact.created_at),
        "due_at": _iso((artifact.created_at or datetime.now(UTC)) + timedelta(days=7)),
        "department_ids": department_ids,
        "policy_key": str(
            metadata.get("review_policy_key") or "artifact-human-review-v1"
        ),
        "policy_version": int(metadata.get("review_policy_version") or 1),
        "assignee": None,
        "batch_eligible": (
            artifact.artifact_kind in _BATCH_KINDS
            and risk == "low"
            and (artifact.confidence is None or artifact.confidence >= _LOW_CONFIDENCE)
            and not blocked
        ),
        "blocked_reasons": blocked,
        "proposal": {
            "content": parsed_content,
            "metadata": metadata,
            "artifact_id": str(artifact.id),
            "asset_id": str(asset.id),
            "asset_revision": revision.revision,
            "conflicts": list(
                linked_conflicts or _artifact_conflicts(artifact.content)
            ),
        },
        "evidence": evidence,
        "publication": {
            "unit_key": f"artifact:{artifact.id}",
            "next_revision": 1,
            "effective_from": "on_approval",
            "acl": dict(asset.acl_reference or {}),
            "rollback": "retire the published KnowledgeUnit release",
            "sop_precedence": artifact.artifact_kind == "procedure_candidate",
        },
    }


def _legacy_item(item: LegacyReviewItem) -> dict[str, Any]:
    tags = dict(item.suggested_tags or {})
    related = tags.pop("_related_ids", [])
    confidence = item.confidence_score
    risk = (
        "low"
        if confidence is not None and confidence >= _LOW_CONFIDENCE and not related
        else "medium"
    )
    return {
        "id": f"legacy:{item.id}",
        "source_group_key": f"legacy:{item.id}",
        "source_asset_id": None,
        "provider": "core.legacy_file_classification",
        "source_type": "document_classification",
        "asset_kind": "document",
        "title": item.file_name,
        "subtitle": item.suggested_category or "未分類",
        "status": item.status,
        "risk_level": risk,
        "confidence": confidence,
        "created_at": _iso(item.created_at),
        "due_at": _iso((item.created_at or datetime.now(UTC)) + timedelta(days=7)),
        "department_ids": [],
        "policy_key": "legacy-watch-folder-review-v1",
        "policy_version": 1,
        "assignee": None,
        "batch_eligible": False,
        "blocked_reasons": [],
        "proposal": {
            "category": item.suggested_category,
            "subcategory": item.suggested_subcategory,
            "tags": tags,
            "reasoning": item.reasoning,
            "related_documents": related,
        },
        "evidence": [
            {
                "id": f"legacy-file:{item.id}",
                "kind": "document",
                "section": item.file_path,
                "deep_link": f"/knowledge/review?item=legacy:{item.id}",
            }
        ],
        "publication": {
            "unit_key": None,
            "next_revision": 1,
            "effective_from": "after ingestion",
            "acl": {"visibility": "tenant", "policy_revision": 1},
            "rollback": "reject or remove the resulting document",
            "sop_precedence": False,
        },
    }


def group_review_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarise candidate rows by the source a human recognises.

    Optional application providers may not yet expose a source key, so their
    item identity is a safe one-item fallback instead of accidentally merging
    unrelated records with the same title.
    """

    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("source_group_key") or f"item:{item['id']}")
        group = groups.setdefault(
            key,
            {
                "key": key,
                "source_asset_id": item.get("source_asset_id"),
                "title": item.get("title") or "未命名來源",
                "asset_kind": item.get("asset_kind") or "unknown",
                "item_count": 0,
                "high_risk_count": 0,
                "low_confidence_count": 0,
                "blocked_reasons": [],
                "item_ids": [],
                "source_confirmable_count": 0,
                "exception_count": 0,
            },
        )
        group["item_count"] += 1
        group["item_ids"].append(item["id"])
        if item.get("risk_level") == "high":
            group["high_risk_count"] += 1
        confidence = item.get("confidence")
        if confidence is not None and float(confidence) < _LOW_CONFIDENCE:
            group["low_confidence_count"] += 1
        group["blocked_reasons"] = sorted(
            set(group["blocked_reasons"]).union(item.get("blocked_reasons") or [])
        )
        if (
            item.get("provider") == "core.asset_artifact"
            and item.get("source_type") in _BATCH_KINDS
            and not item.get("blocked_reasons")
        ):
            group["source_confirmable_count"] += 1
        else:
            group["exception_count"] += 1
    for group in groups.values():
        group["source_approval_ready"] = group["source_confirmable_count"] > 0
    return list(groups.values())


def _pack_providers(db: Session, tenant_id: UUID) -> list[Any]:
    registry = build_pack_registry()
    context = PackTenantContext(tenant_id=tenant_id, db=db)
    providers: list[Any] = []
    for _pack_key, contribution in registry.enabled_review_providers(context=context):
        try:
            provider_type = _load(contribution.provider_path)
            providers.append(provider_type())
        except Exception:
            logger.exception(
                "optional review provider failed closed: %s",
                contribution.provider_key,
            )
    return providers


def list_review_items(db: Session, *, current_user: User) -> list[dict[str, Any]]:
    tenant_id = current_user.tenant_id
    reviewable_revision_ids = {
        row[0]
        for row in db.query(IngestionJob.asset_revision_id).filter(
            IngestionJob.tenant_id == tenant_id,
            IngestionJob.status == "review_required",
        )
    }
    rows = []
    if reviewable_revision_ids:
        rows = (
            db.query(DerivedArtifact, AssetRevision, SourceAsset)
            .join(
                AssetRevision,
                (AssetRevision.tenant_id == DerivedArtifact.tenant_id)
                & (AssetRevision.id == DerivedArtifact.asset_revision_id),
            )
            .join(
                SourceAsset,
                (SourceAsset.tenant_id == AssetRevision.tenant_id)
                & (SourceAsset.id == AssetRevision.asset_id),
            )
            .filter(
                DerivedArtifact.tenant_id == tenant_id,
                DerivedArtifact.asset_revision_id.in_(reviewable_revision_ids),
                DerivedArtifact.quality_state == "review_required",
                SourceAsset.tombstoned_at.is_(None),
            )
            .order_by(DerivedArtifact.created_at.desc())
            .limit(500)
            .all()
        )
    visible = [
        row
        for row in rows
        if asset_access_allows(
            db, row[2], authz=AuthorizationContext.from_user(current_user)
        )
    ]
    conflict_reports: dict[tuple[UUID, str], list[dict[str, Any]]] = {}
    for artifact, _revision, _asset in visible:
        if artifact.artifact_kind != "sop_conflict_report":
            continue
        procedure_id = str(
            (artifact.metadata_json or {}).get("procedure_artifact_id") or ""
        )
        if procedure_id:
            conflict_reports[(artifact.asset_revision_id, procedure_id)] = (
                _artifact_conflicts(artifact.content)
            )
    # Technical timeline/segmentation records remain auditable but are not
    # independent business decisions.  Showing them as 32 extra approvals was
    # both misleading and capable of leaving the ingestion job stuck.
    visible = [
        row for row in visible if row[0].artifact_kind not in _NON_ACTIONABLE_KINDS
    ]
    artifact_ids = [row[0].id for row in visible]
    spans_by_artifact: dict[UUID, list[EvidenceSpan]] = {}
    if artifact_ids:
        for span in db.query(EvidenceSpan).filter(
            EvidenceSpan.tenant_id == tenant_id,
            EvidenceSpan.artifact_id.in_(artifact_ids),
        ):
            spans_by_artifact.setdefault(span.artifact_id, []).append(span)
    items = [
        _artifact_item(
            artifact,
            revision,
            asset,
            spans_by_artifact.get(artifact.id, []),
            current_user=current_user,
            linked_conflicts=conflict_reports.get(
                (artifact.asset_revision_id, str(artifact.id))
            ),
        )
        for artifact, revision, asset in visible
    ]
    legacy = (
        db.query(LegacyReviewItem)
        .filter(
            LegacyReviewItem.tenant_id == tenant_id,
            LegacyReviewItem.status == "pending",
        )
        .order_by(LegacyReviewItem.created_at.desc())
        .limit(200)
        .all()
    )
    items.extend(_legacy_item(item) for item in legacy)
    for provider in _pack_providers(db, tenant_id):
        try:
            items.extend(provider.list_items(db=db, current_user=current_user))
        except Exception:
            logger.exception(
                "optional review provider listing failed closed: %s",
                provider.provider_key,
            )
    return items


def get_review_item(db: Session, *, current_user: User, item_id: str) -> dict[str, Any]:
    item = next(
        (
            row
            for row in list_review_items(db, current_user=current_user)
            if row["id"] == item_id
        ),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="review item not found")
    return item


def _audit(
    db: Session,
    *,
    current_user: User,
    item_id: str,
    decision: str,
    evidence: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            action="knowledge_review_decision",
            target_type="review_item",
            target_id=item_id,
            detail_json={"decision": decision, **evidence},
        )
    )


def _decide_artifact(
    db: Session,
    *,
    current_user: User,
    artifact_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    row = (
        db.query(DerivedArtifact, AssetRevision, SourceAsset)
        .join(
            AssetRevision,
            (AssetRevision.tenant_id == DerivedArtifact.tenant_id)
            & (AssetRevision.id == DerivedArtifact.asset_revision_id),
        )
        .join(
            SourceAsset,
            (SourceAsset.tenant_id == AssetRevision.tenant_id)
            & (SourceAsset.id == AssetRevision.asset_id),
        )
        .filter(
            DerivedArtifact.tenant_id == current_user.tenant_id,
            DerivedArtifact.id == artifact_id,
        )
        .with_for_update()
        .first()
    )
    if row is None or not asset_access_allows(
        db, row[2], authz=AuthorizationContext.from_user(current_user)
    ):
        raise HTTPException(status_code=404, detail="review item not found")
    artifact, revision, asset = row
    decision = payload["decision"]
    if artifact.artifact_kind == "procedure_candidate":
        from app.api.v1.endpoints.video_assets import (
            ArtifactReviewRequest,
            review_video_procedure,
        )

        conflict_artifact = (
            db.query(DerivedArtifact)
            .filter(
                DerivedArtifact.tenant_id == current_user.tenant_id,
                DerivedArtifact.asset_revision_id == revision.id,
                DerivedArtifact.artifact_kind == "sop_conflict_report",
            )
            .order_by(DerivedArtifact.created_at.desc())
            .first()
        )
        linked_conflicts = (
            _artifact_conflicts(conflict_artifact.content)
            if conflict_artifact is not None
            and str(
                (conflict_artifact.metadata_json or {}).get("procedure_artifact_id")
                or ""
            )
            == str(artifact.id)
            else []
        )
        spans = (
            db.query(EvidenceSpan)
            .filter(
                EvidenceSpan.tenant_id == current_user.tenant_id,
                EvidenceSpan.artifact_id == artifact.id,
            )
            .all()
        )
        item = _artifact_item(
            artifact,
            revision,
            asset,
            spans,
            current_user=current_user,
            linked_conflicts=linked_conflicts,
        )
        hard_blocks = [
            reason
            for reason in item["blocked_reasons"]
            if reason != "unresolved_sop_conflicts"
        ]
        if decision == "approved" and hard_blocks:
            raise HTTPException(
                status_code=409,
                detail={"code": hard_blocks[0], "blocked_reasons": hard_blocks},
            )
        return review_video_procedure(
            artifact_id,
            ArtifactReviewRequest(
                decision=decision,
                notes=payload.get("notes"),
                conflict_resolutions=payload.get("conflict_resolutions") or {},
                acknowledge_high_risk=bool(payload.get("acknowledge_high_risk")),
            ),
            db,
            current_user,
        )
    if artifact.quality_state != "review_required":
        existing = (
            db.query(ArtifactReviewDecision)
            .filter(
                ArtifactReviewDecision.tenant_id == current_user.tenant_id,
                ArtifactReviewDecision.artifact_id == artifact.id,
            )
            .first()
        )
        if existing is not None and existing.decision == decision:
            return {
                "item_id": f"artifact:{artifact.id}",
                "decision": decision,
                "knowledge_authority": (existing.resolution_json or {}).get(
                    "knowledge_authority"
                ),
                "idempotent": True,
            }
        if existing is not None:
            raise HTTPException(status_code=409, detail="artifact already reviewed")
        raise HTTPException(status_code=409, detail="artifact is not reviewable")
    spans = (
        db.query(EvidenceSpan)
        .filter(
            EvidenceSpan.tenant_id == current_user.tenant_id,
            EvidenceSpan.artifact_id == artifact.id,
        )
        .all()
    )
    item = _artifact_item(artifact, revision, asset, spans, current_user=current_user)
    if decision == "approved":
        if item["blocked_reasons"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": item["blocked_reasons"][0],
                    "blocked_reasons": item["blocked_reasons"],
                },
            )
        if _artifact_risk(artifact) == "high" and not payload.get(
            "acknowledge_high_risk"
        ):
            raise HTTPException(
                status_code=409, detail={"code": "high_risk_acknowledgement_required"}
            )
        if (
            artifact.confidence is not None
            and artifact.confidence < _LOW_CONFIDENCE
            and not payload.get("acknowledge_low_confidence")
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "low_confidence_acknowledgement_required"},
            )
    authority: dict[str, Any] | None = None
    if decision == "approved":
        from app.services.knowledge_authority import publish_knowledge_unit

        locator = _locator_dict(spans[0], asset) if spans else {}
        publish_content = artifact.content or json.dumps(
            artifact.metadata_json or {}, ensure_ascii=False
        )
        if artifact.artifact_kind == "transcript_correction":
            try:
                correction = json.loads(artifact.content or "{}")
                publish_content = str(correction.get("candidate") or "").strip()
            except (json.JSONDecodeError, TypeError):
                publish_content = ""
            if not publish_content:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "invalid_transcript_correction"},
                )
        authority = publish_knowledge_unit(
            db,
            tenant_id=current_user.tenant_id,
            unit_key=f"artifact:{artifact.id}",
            unit_type=_knowledge_unit_type(artifact.artifact_kind),
            title=asset.title,
            content=publish_content,
            authority_class="human_reviewed_artifact",
            acl_snapshot=dict(asset.acl_reference or {}),
            source_resource_type="derived_artifact",
            source_resource_id=str(artifact.id),
            source_asset_id=asset.id,
            source_asset_revision_id=revision.id,
            source_artifact_id=artifact.id,
            risk_level=("high" if _artifact_risk(artifact) == "high" else "normal"),
            metadata={
                "source_asset_id": str(asset.id),
                "artifact_kind": artifact.artifact_kind,
                "locator": locator,
                "deep_link": locator.get("deep_link")
                or f"/knowledge/assets/{asset.id}",
            },
            created_by=current_user.id,
            gate_evidence={
                "reviewer_id": str(current_user.id),
                "decision": decision,
                "acknowledged_low_confidence": bool(
                    payload.get("acknowledge_low_confidence")
                ),
            },
        )
    db.add(
        ArtifactReviewDecision(
            tenant_id=current_user.tenant_id,
            artifact_id=artifact.id,
            asset_revision_id=revision.id,
            decision=decision,
            notes=payload.get("notes"),
            reviewer_id=current_user.id,
            resolution_json={"knowledge_authority": authority} if authority else {},
        )
    )
    artifact.quality_state = "ready" if decision == "approved" else "rejected"
    db.flush()
    remaining = (
        db.query(DerivedArtifact.id)
        .filter(
            DerivedArtifact.tenant_id == current_user.tenant_id,
            DerivedArtifact.asset_revision_id == revision.id,
            DerivedArtifact.quality_state == "review_required",
            ~DerivedArtifact.artifact_kind.in_(_NON_ACTIONABLE_KINDS),
        )
        .first()
    )
    if remaining is None:
        # Structural artifacts inherit the source decision; they are retained
        # for traceability but never published as standalone user knowledge.
        structural_state = "ready" if decision == "approved" else "rejected"
        (
            db.query(DerivedArtifact)
            .filter(
                DerivedArtifact.tenant_id == current_user.tenant_id,
                DerivedArtifact.asset_revision_id == revision.id,
                DerivedArtifact.quality_state == "review_required",
                DerivedArtifact.artifact_kind.in_(_NON_ACTIONABLE_KINDS),
            )
            .update(
                {DerivedArtifact.quality_state: structural_state},
                synchronize_session=False,
            )
        )
        has_approved = (
            db.query(ArtifactReviewDecision.id)
            .filter(
                ArtifactReviewDecision.tenant_id == current_user.tenant_id,
                ArtifactReviewDecision.asset_revision_id == revision.id,
                ArtifactReviewDecision.decision == "approved",
            )
            .first()
            is not None
        )
        job = (
            db.query(IngestionJob)
            .filter(
                IngestionJob.tenant_id == current_user.tenant_id,
                IngestionJob.asset_revision_id == revision.id,
                IngestionJob.status == "review_required",
            )
            .with_for_update()
            .first()
        )
        if job is not None:
            from app.services.ingestion_orchestrator import get_ingestion_orchestrator

            get_ingestion_orchestrator().transition(
                db,
                job,
                to_status="ready",
                phase="published" if has_approved else "review_rejected",
                quality_state="ready" if has_approved else "rejected",
                readiness={
                    "searchable": has_approved,
                    "reviewed_by": str(current_user.id),
                },
            )
        revision.ingestion_status = "ready"
        asset.status = "active"
    return {
        "item_id": f"artifact:{artifact.id}",
        "decision": decision,
        "knowledge_authority": authority,
    }


def decide_source_group(
    db: Session,
    *,
    current_user: User,
    source_asset_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Confirm literal extractive output for one source in one transaction.

    Inferred rules, procedures, equipment states and application-pack items are
    deliberately left in the exception queue.  This keeps the common upload
    path usable without weakening high-risk governance.
    """
    if payload.get("decision") not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="invalid review decision")
    candidates = [
        item
        for item in list_review_items(db, current_user=current_user)
        if item.get("source_asset_id") == str(source_asset_id)
        and item.get("provider") == "core.asset_artifact"
        and item.get("source_type") in _BATCH_KINDS
    ]
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail={"code": "source_confirmation_not_found"},
        )
    blocked = {
        reason for item in candidates for reason in (item.get("blocked_reasons") or [])
    }
    if blocked:
        raise HTTPException(
            status_code=409,
            detail={
                "code": sorted(blocked)[0],
                "blocked_reasons": sorted(blocked),
            },
        )
    low_confidence = [
        item
        for item in candidates
        if item.get("confidence") is not None
        and float(item["confidence"]) < _LOW_CONFIDENCE
    ]
    if (
        payload["decision"] == "approved"
        and low_confidence
        and not payload.get("acknowledge_low_confidence")
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "low_confidence_acknowledgement_required",
                "item_ids": [item["id"] for item in low_confidence],
            },
        )
    results = []
    try:
        for item in candidates:
            results.append(
                decide_review_item(
                    db,
                    current_user=current_user,
                    item_id=item["id"],
                    payload={
                        **payload,
                        "acknowledge_high_risk": False,
                        "conflict_resolutions": {},
                    },
                    commit=False,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "source_asset_id": str(source_asset_id),
        "decision": payload["decision"],
        "decided_count": len(results),
        "results": results,
    }


def decide_review_item(
    db: Session,
    *,
    current_user: User,
    item_id: str,
    payload: dict[str, Any],
    commit: bool = True,
) -> dict[str, Any]:
    decision = payload.get("decision")
    if decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="invalid review decision")
    prefix, separator, raw_id = item_id.partition(":")
    if not separator:
        raise HTTPException(status_code=404, detail="review item not found")
    try:
        object_id = UUID(raw_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="review item not found") from exc
    try:
        snapshot = get_review_item(db, current_user=current_user, item_id=item_id)
    except HTTPException as exc:
        if exc.status_code != 404 or prefix not in {"artifact", "legacy"}:
            raise
        snapshot = None

    audit_evidence = {
        "provider": (
            snapshot["provider"]
            if snapshot
            else (
                "core.legacy_file_classification"
                if prefix == "legacy"
                else "core.asset_artifact"
            )
        ),
        "source_type": snapshot["source_type"] if snapshot else None,
        "risk_level": snapshot["risk_level"] if snapshot else None,
        "policy_key": snapshot["policy_key"] if snapshot else None,
        "policy_version": snapshot["policy_version"] if snapshot else None,
        "evidence_ids": [row["id"] for row in snapshot["evidence"]] if snapshot else [],
        "acknowledged_high_risk": bool(payload.get("acknowledge_high_risk")),
        "acknowledged_low_confidence": bool(payload.get("acknowledge_low_confidence")),
        "conflict_resolution_ids": sorted(
            (payload.get("conflict_resolutions") or {}).keys()
        ),
    }
    if prefix == "artifact":
        result = _decide_artifact(
            db,
            current_user=current_user,
            artifact_id=object_id,
            payload=payload,
        )
        # The video compatibility service commits its own transaction.
        if not result.get("idempotent"):
            _audit(
                db,
                current_user=current_user,
                item_id=item_id,
                decision=decision,
                evidence=audit_evidence,
            )
        if commit:
            db.commit()
        return result
    if prefix == "legacy":
        item = (
            db.query(LegacyReviewItem)
            .filter(
                LegacyReviewItem.tenant_id == current_user.tenant_id,
                LegacyReviewItem.id == object_id,
            )
            .first()
        )
        if item is None:
            raise HTTPException(status_code=404, detail="review item not found")
        same_decision = (
            decision == "approved"
            and item.status in {"approved", "modified", "processing", "indexed"}
        ) or (decision == "rejected" and item.status == "rejected")
        if same_decision:
            return {"item_id": item_id, "decision": decision, "idempotent": True}
        if item.status != "pending":
            raise HTTPException(status_code=409, detail="review item already reviewed")
        manager = ReviewQueueManager(db)
        ok = (
            manager.approve(object_id, current_user.id)
            if decision == "approved"
            else manager.reject(object_id, payload.get("notes") or "", current_user.id)
        )
        if not ok:
            raise HTTPException(status_code=409, detail="review item is not pending")
        _audit(
            db,
            current_user=current_user,
            item_id=item_id,
            decision=decision,
            evidence=audit_evidence,
        )
        if commit:
            db.commit()
        return {"item_id": item_id, "decision": decision}
    for provider in _pack_providers(db, current_user.tenant_id):
        if prefix == provider.item_prefix:
            result = provider.decide(
                db=db,
                current_user=current_user,
                object_id=object_id,
                payload=payload,
            )
            if not result.get("idempotent"):
                _audit(
                    db,
                    current_user=current_user,
                    item_id=item_id,
                    decision=decision,
                    evidence=audit_evidence,
                )
            if commit:
                db.commit()
            return result
    raise HTTPException(status_code=404, detail="review item not found")
