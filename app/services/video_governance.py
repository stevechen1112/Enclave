"""Evidence classification, formal-SOP conflict checks and safe publication."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, DerivedArtifact, EvidenceSpan, SourceAsset
from app.services.sop_conflict import SOPConflictChecker
from app.services.video_processing import _ensure_video_evidence, _upsert_artifact

_PRECONDITION_TERMS = ("必須先", "先確認", "之前", "前置", "事先", "先檢查")
_DECISION_TERMS = ("如果", "若", "當", "否則", "才能", "則", "視", "依")
_RISK_TERMS = ("危險", "風險", "注意", "燙傷", "夾傷", "觸電", "爆炸", "漏電")
_EXCEPTION_TERMS = ("例外", "除非", "無法", "故障", "異常時", "特殊情況")
_PROHIBITION_TERMS = ("禁止", "不得", "不可", "嚴禁", "切勿")
_EQUIPMENT_RE = re.compile(r"\b[A-Z]{1,5}[-_]?\d{2,}(?:[-_]\d+)?\b", re.IGNORECASE)


@dataclass(frozen=True)
class StructuredProcedure:
    payload: dict[str, Any]
    confidence: float | None
    start_ms: int
    end_ms: int


def _evidence_items(db: Session, revision: AssetRevision) -> list[dict[str, Any]]:
    artifacts = (
        db.query(DerivedArtifact)
        .filter(
            DerivedArtifact.tenant_id == revision.tenant_id,
            DerivedArtifact.asset_revision_id == revision.id,
            DerivedArtifact.artifact_kind.in_(
                ("transcript_segment", "ocr_region", "action_event", "equipment_state")
            ),
        )
        .order_by(DerivedArtifact.created_at.asc())
        .all()
    )
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, int]] = set()
    for artifact in artifacts:
        text = str(artifact.content or "").strip()
        if not text:
            continue
        span = (
            db.query(EvidenceSpan)
            .filter(
                EvidenceSpan.tenant_id == revision.tenant_id,
                EvidenceSpan.artifact_id == artifact.id,
                EvidenceSpan.asset_revision_id == revision.id,
            )
            .order_by(EvidenceSpan.start_ms.asc())
            .first()
        )
        if span is None:
            continue
        start_ms = int(span.start_ms or 0)
        end_ms = int(span.end_ms or start_ms + 1)
        identity = (artifact.artifact_kind, text, start_ms, end_ms)
        if identity in seen:
            continue
        seen.add(identity)
        rows.append(
            {
                "text": text,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "evidence_artifact_id": str(artifact.id),
                "evidence_kind": artifact.artifact_kind,
                "confidence": artifact.confidence,
                "deep_link": f"/knowledge/videos/{revision.asset_id}?t={start_ms}",
            }
        )
    return sorted(rows, key=lambda row: (row["start_ms"], row["text"]))


def build_structured_procedure(db: Session, revision: AssetRevision) -> StructuredProcedure | None:
    items = _evidence_items(db, revision)
    if not items:
        return None
    asset = (
        db.query(SourceAsset)
        .filter(
            SourceAsset.tenant_id == revision.tenant_id,
            SourceAsset.id == revision.asset_id,
        )
        .one()
    )

    semantic_items = list(
        {
            (item["text"], item["start_ms"], item["end_ms"]): item
            for item in items
        }.values()
    )

    def matching(terms: tuple[str, ...]) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(item)
            for item in semantic_items
            if any(term in item["text"] for term in terms)
        ]

    actions = [item for item in items if item["evidence_kind"] == "action_event"]
    if not actions:
        actions = [item for item in items if item["evidence_kind"] == "transcript_segment"]
    steps = [
        {"sequence": index, **copy.deepcopy(item)}
        for index, item in enumerate(actions[:30], start=1)
    ]
    equipment = sorted(
        {
            value.upper().replace("_", "-")
            for item in semantic_items
            for value in _EQUIPMENT_RE.findall(item["text"])
        }
        | {
            str(value)
            for value in (asset.metadata_json or {}).get("equipment_ids", [])
            if str(value).strip()
        }
    )
    confidences = [
        float(item["confidence"])
        for item in semantic_items
        if item.get("confidence") is not None
    ]
    payload = {
        "schema_version": "2.0",
        "title": f"{asset.title} — 作業程序候選",
        "summary": "由影片證據結構化；人員核准且正式 SOP 衝突處置前不得發布。",
        "applicable_equipment": equipment,
        "applicable_roles": list((asset.metadata_json or {}).get("applicable_roles", [])),
        "steps": steps,
        "preconditions": matching(_PRECONDITION_TERMS),
        "decision_rules": matching(_DECISION_TERMS),
        "risks": matching(_RISK_TERMS),
        "exceptions": matching(_EXCEPTION_TERMS),
        "prohibited_actions": matching(_PROHIBITION_TERMS),
        "source_asset_id": str(asset.id),
        "source_revision_id": str(revision.id),
        "source_revision": revision.revision,
        "effective_from": revision.effective_from.isoformat() if revision.effective_from else None,
    }
    return StructuredProcedure(
        payload=payload,
        confidence=(sum(confidences) / len(confidences) if confidences else None),
        start_ms=min(item["start_ms"] for item in semantic_items),
        end_ms=max(item["end_ms"] for item in semantic_items),
    )


def load_formal_sop_documents(db: Session, *, tenant_id: UUID) -> list[dict[str, Any]]:
    from app.models.document import Document, DocumentChunk

    documents = (
        db.query(Document)
        .filter(
            Document.tenant_id == tenant_id,
            Document.tombstoned_at.is_(None),
            Document.status == "completed",
            or_(
                Document.filename.ilike("%SOP%"),
                Document.filename.ilike("%作業標準%"),
                Document.filename.ilike("%標準作業%"),
            ),
        )
        .order_by(Document.updated_at.desc(), Document.created_at.desc())
        .limit(20)
        .all()
    )
    rows: list[dict[str, Any]] = []
    for document in documents:
        chunks = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document.id,
                DocumentChunk.document_revision == int(document.version or 1),
            )
            .order_by(DocumentChunk.chunk_index.asc())
            .limit(80)
            .all()
        )
        texts = [str(chunk.text or "").strip() for chunk in chunks if str(chunk.text or "").strip()]
        if not texts:
            continue
        rows.append(
            {
                "id": str(document.id),
                "revision": int(document.version or 1),
                "title": document.filename,
                "steps": [text for text in texts if any(term in text for term in ("步驟", "操作", "1.", "2."))] or texts[:10],
                "applicable_equipment": sorted(
                    {match.upper().replace("_", "-") for text in texts for match in _EQUIPMENT_RE.findall(text)}
                ),
                "cautions": [text for text in texts if any(term in text for term in (*_RISK_TERMS, *_PROHIBITION_TERMS))],
                "evidence": [
                    {
                        "document_id": str(document.id),
                        "document_revision": int(document.version or 1),
                        "chunk_id": str(chunk.id),
                        "chunk_index": chunk.chunk_index,
                        "text": str(chunk.text or "").strip(),
                    }
                    for chunk in chunks
                    if str(chunk.text or "").strip()
                ],
            }
        )
    return rows


def build_sop_conflict_report(
    procedure: dict[str, Any], sop_documents: list[dict[str, Any]]
) -> dict[str, Any]:
    card = SimpleNamespace(
        steps=[str(item.get("text") or "") for item in procedure.get("steps", [])],
        equipment_ids=list(procedure.get("applicable_equipment", [])),
        cautions=[
            str(item.get("text") or "")
            for key in ("risks", "prohibited_actions")
            for item in procedure.get(key, [])
        ],
        recommended_actions=[],
    )
    conflicts = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in SOPConflictChecker().check_conflicts(card, sop_documents):
        payload = record.to_dict()
        key = (
            str(payload.get("conflict_type") or ""),
            str(payload.get("knowhow_field") or ""),
            str(payload.get("sop_value") or ""),
            str(payload.get("knowhow_value") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        payload["preferred"] = "sop"
        payload["resolved"] = False
        sop_value = str(payload.get("sop_value") or "")
        evidence = next(
            (
                evidence
                for document in sop_documents
                for evidence in list(document.get("evidence") or [])
                if sop_value
                and (
                    sop_value in str(evidence.get("text") or "")
                    or str(evidence.get("text") or "") in sop_value
                )
            ),
            None,
        )
        payload["sop_evidence"] = evidence
        identity = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        payload["id"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        conflicts.append(payload)
    return {
        "schema_version": "1.0",
        "authority_policy": "formal_sop_wins",
        "authority_basis": "completed_current_document_revision",
        "sop_sources": [
            {"id": row.get("id"), "revision": row.get("revision"), "title": row.get("title")}
            for row in sop_documents
        ],
        "conflicts": conflicts,
        "checked": True,
    }


def apply_sop_precedence(
    procedure: dict[str, Any],
    conflicts: list[dict[str, Any]],
    resolutions: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    published = copy.deepcopy(procedure)
    unresolved: list[str] = []
    authority_overrides: list[dict[str, Any]] = []
    for conflict in conflicts:
        conflict_id = str(conflict.get("id") or "")
        if resolutions.get(conflict_id) != "sop_wins":
            unresolved.append(conflict_id)
            continue
        field = str(conflict.get("knowhow_field") or "")
        sop_value = str(conflict.get("sop_value") or "").strip()
        match = re.fullmatch(r"step\[(\d+)]", field)
        applied = False
        if match and sop_value:
            index = int(match.group(1))
            steps = list(published.get("steps") or [])
            if index < len(steps):
                steps[index]["text"] = sop_value
                steps[index]["authority_override"] = "formal_sop"
                applied = True
        elif field in {"caution", "prohibition"} and sop_value:
            published.setdefault("prohibited_actions", []).append(
                {"text": sop_value, "authority_override": "formal_sop"}
            )
            applied = True
        elif field == "applicable_equipment" and sop_value:
            published["applicable_equipment"] = [
                value.strip() for value in sop_value.split(",") if value.strip()
            ]
            applied = True
        if not applied:
            unresolved.append(conflict_id)
            continue
        authority_overrides.append(
            {"conflict_id": conflict_id, "resolution": "sop_wins", "sop_value": sop_value}
        )
    published["authority_overrides"] = authority_overrides
    published["governance_state"] = "approved_with_sop_precedence" if authority_overrides else "approved"
    return published, unresolved


def project_governed_video_procedure(
    db: Session,
    revision: AssetRevision,
    *,
    sop_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    structured = build_structured_procedure(db, revision)
    if structured is None:
        return {"procedure_artifact_id": None, "conflict_count": 0, "high_risk": False}
    procedure = _upsert_artifact(
        db,
        revision,
        artifact_kind="procedure_candidate",
        content=json.dumps(structured.payload, ensure_ascii=False),
        confidence=structured.confidence,
        quality_state="review_required",
        metadata={
            "schema_version": "2.0",
            "step_count": len(structured.payload["steps"]),
            "high_risk": bool(structured.payload["risks"] or structured.payload["prohibited_actions"]),
        },
        provider="core.video_governance",
        provider_version="1.0",
    )
    _ensure_video_evidence(
        db,
        revision,
        procedure,
        start_ms=structured.start_ms,
        end_ms=structured.end_ms,
    )
    sop_documents = sop_documents if sop_documents is not None else load_formal_sop_documents(
        db, tenant_id=revision.tenant_id
    )
    report = build_sop_conflict_report(structured.payload, sop_documents)
    conflict_artifact = _upsert_artifact(
        db,
        revision,
        artifact_kind="sop_conflict_report",
        content=json.dumps(report, ensure_ascii=False),
        quality_state="review_required",
        metadata={
            "procedure_artifact_id": str(procedure.id),
            "conflict_count": len(report["conflicts"]),
            "sop_source_count": len(report["sop_sources"]),
        },
        provider="core.sop_conflict",
        provider_version="1.0",
    )
    _ensure_video_evidence(
        db,
        revision,
        conflict_artifact,
        start_ms=structured.start_ms,
        end_ms=structured.end_ms,
    )
    return {
        "procedure_artifact_id": str(procedure.id),
        "conflict_report_artifact_id": str(conflict_artifact.id),
        "conflict_count": len(report["conflicts"]),
        "high_risk": bool(structured.payload["risks"] or structured.payload["prohibited_actions"]),
    }
