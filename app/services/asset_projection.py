"""Phase B compatibility projection into canonical multi-modal assets.

The existing Document and MKA capture models remain operational during the
dual-write period. This service owns the only supported bridge into the new
asset tables. It never commits: callers keep the legacy row and its canonical
projection in one transaction.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.asset import (
    AssetRevision,
    DerivedArtifact,
    EvidenceSpan,
    SourceAsset,
)

_SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")

_ASSET_KIND_BY_EXTENSION = {
    **{ext: "spreadsheet" for ext in ("csv", "tsv", "xls", "xlsx", "ods")},
    **{
        ext: "image"
        for ext in ("png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp")
    },
    **{ext: "audio" for ext in ("wav", "mp3", "m4a", "aac", "ogg", "flac", "webm")},
    **{ext: "video" for ext in ("mp4", "mov", "mkv", "avi", "mpeg", "mpg")},
    **{ext: "email" for ext in ("eml", "msg")},
    **{ext: "web_page" for ext in ("html", "htm")},
    **{ext: "dataset" for ext in ("parquet", "ndjson")},
}

_SEMANTIC_ASSET_KINDS = {
    "spreadsheet": "spreadsheet",
    "image": "image",
    "audio": "audio",
    "video": "video",
    "email": "email",
    "web_page": "web_page",
    "dataset": "dataset",
    "document": "document",
}


class AssetProjectionConflict(RuntimeError):
    """Legacy state conflicts with an already immutable canonical revision."""


@dataclass(frozen=True)
class AssetProjectionResult:
    asset: SourceAsset
    revision: AssetRevision | None
    asset_created: bool
    revision_created: bool


def normalize_sha256(value: Any) -> str | None:
    match = _SHA256_RE.fullmatch(str(value or "").strip())
    return match.group(1).lower() if match else None


def infer_asset_kind(*, filename: str, file_type: str | None) -> str:
    extension = str(file_type or "").lower().lstrip(".")
    if extension in _SEMANTIC_ASSET_KINDS:
        return _SEMANTIC_ASSET_KINDS[extension]
    if not extension and "." in (filename or ""):
        extension = filename.rsplit(".", 1)[-1].lower()
    return _ASSET_KIND_BY_EXTENSION.get(extension, "document")


def document_quality_state(metadata: dict[str, Any] | None) -> str:
    """Map parser quality into the canonical human-review policy."""

    values = dict(metadata or {})
    if values.get("review_required") or values.get("locator_fallback"):
        return "review_required"
    structure = values.get("structure_policy")
    if isinstance(structure, dict) and structure.get("hidden_sheets"):
        return "review_required"
    if values.get("errors"):
        return "review_required"
    score = values.get("quality_score")
    if isinstance(score, (int, float)) and float(score) < 0.5:
        return "review_required"
    if values.get("ocr_used"):
        confidence = values.get("ocr_confidence")
        if isinstance(confidence, (int, float)) and float(confidence) < 0.7:
            return "review_required"
    extension = str(values.get("file_extension") or "").lower()
    content_hash = str(values.get("content_hash") or "")
    if extension and content_hash:
        from app.services.input_quality import requires_human_review

        if requires_human_review(
            extension,
            confidence=float(score) if isinstance(score, (int, float)) else None,
            content_hash=content_hash,
            fallback_used=bool(values.get("locator_fallback")),
            sampling_enabled=bool(values.get("quality_sampling_enabled", False)),
        ):
            return "review_required"
    return "ready"


def infer_media_type(*, filename: str, file_type: str | None) -> str:
    guessed, _ = mimetypes.guess_type(filename or "")
    if guessed:
        return guessed
    extension = str(file_type or "").lower().lstrip(".")
    if extension == "pdf":
        return "application/pdf"
    if extension in {"txt", "md"}:
        return "text/plain"
    return "application/octet-stream"


def _document_source_identity(document: Any) -> tuple[str, str | None]:
    source_system = str(getattr(document, "source_system", "") or "").strip()
    source_record_id = str(getattr(document, "source_record_id", "") or "").strip()
    if source_system and source_record_id:
        return source_system, source_record_id
    return "upload", None


def project_document(
    db: Session,
    document: Any,
    *,
    content_uri: str | None = None,
    content_hash: str | None = None,
    ingestion_status: str | None = None,
) -> AssetProjectionResult:
    """Idempotently dual-write a Document and its current immutable revision."""

    tenant_id = UUID(str(document.tenant_id))
    asset: SourceAsset | None = None
    if getattr(document, "source_asset_id", None):
        asset = (
            db.query(SourceAsset)
            .filter(
                SourceAsset.tenant_id == tenant_id,
                SourceAsset.id == document.source_asset_id,
            )
            .first()
        )
        if asset is None:
            raise AssetProjectionConflict("document references a missing source asset")

    asset_created = asset is None
    if asset is None:
        from app.services.asset_visibility import canonical_asset_acl

        source_system, source_record_id = _document_source_identity(document)
        department_ids = [document.department_id] if document.department_id else []
        asset = SourceAsset(
            tenant_id=tenant_id,
            asset_kind=infer_asset_kind(
                filename=document.filename, file_type=document.file_type
            ),
            title=document.filename,
            source_system=source_system,
            source_record_id=source_record_id,
            data_classification="internal",
            acl_reference={
                **canonical_asset_acl(
                    owner_subject_id=getattr(document, "uploaded_by", None),
                    visibility="restricted" if department_ids else "tenant",
                    allowed_department_ids=department_ids,
                ),
                "department_id": (
                    str(document.department_id) if document.department_id else None
                ),
                "legacy_policy": "document_visibility_v1",
            },
            metadata_json={
                "legacy_resource_type": "document",
                "legacy_document_id": str(document.id),
                "genre": getattr(document, "genre", None),
            },
            created_by=getattr(document, "uploaded_by", None),
            status="pending",
        )
        db.add(asset)
        db.flush()
        document.source_asset_id = asset.id

    if getattr(document, "tombstoned_at", None) is not None:
        asset.status = "tombstoned"
        asset.tombstoned_at = document.tombstoned_at
        current = None
        if asset.current_revision:
            current = (
                db.query(AssetRevision)
                .filter(
                    AssetRevision.tenant_id == tenant_id,
                    AssetRevision.asset_id == asset.id,
                    AssetRevision.revision == asset.current_revision,
                )
                .first()
            )
        return AssetProjectionResult(asset, current, asset_created, False)
    else:
        from app.services.asset_visibility import canonical_asset_acl

        asset.title = document.filename
        department_ids = [document.department_id] if document.department_id else []
        asset.acl_reference = {
            **dict(asset.acl_reference or {}),
            **canonical_asset_acl(
                owner_subject_id=getattr(document, "uploaded_by", None),
                visibility="restricted" if department_ids else "tenant",
                allowed_department_ids=department_ids,
            ),
            "department_id": (
                str(document.department_id) if document.department_id else None
            ),
        }

    uri = str(content_uri or getattr(document, "file_path", "") or "").strip()
    digest = normalize_sha256(content_hash or getattr(document, "content_hash", None))
    if not uri or digest is None:
        return AssetProjectionResult(asset, None, asset_created, False)

    revision_number = max(1, int(getattr(document, "version", 1) or 1))
    revision = (
        db.query(AssetRevision)
        .filter(
            AssetRevision.tenant_id == tenant_id,
            AssetRevision.asset_id == asset.id,
            AssetRevision.revision == revision_number,
        )
        .first()
    )
    revision_created = revision is None
    if revision is not None:
        if revision.content_hash != digest or revision.content_uri != uri:
            raise AssetProjectionConflict(
                "document revision conflicts with immutable asset revision"
            )
        if ingestion_status:
            revision.ingestion_status = ingestion_status
    else:
        previous = None
        if asset.current_revision:
            previous = (
                db.query(AssetRevision.id)
                .filter(
                    AssetRevision.tenant_id == tenant_id,
                    AssetRevision.asset_id == asset.id,
                    AssetRevision.revision == asset.current_revision,
                )
                .scalar()
            )
        revision = AssetRevision(
            tenant_id=tenant_id,
            asset_id=asset.id,
            revision=revision_number,
            media_type=infer_media_type(
                filename=document.filename, file_type=document.file_type
            ),
            content_uri=uri,
            content_hash=digest,
            external_version=getattr(document, "external_version", None),
            byte_size=getattr(document, "file_size", None),
            ingestion_status=ingestion_status
            or (
                "ready"
                if getattr(document, "status", None) == "completed"
                else "pending"
            ),
            metadata_json={
                "legacy_document_id": str(document.id),
                "legacy_document_revision": revision_number,
            },
            supersedes_revision_id=previous,
            created_by=getattr(document, "uploaded_by", None),
        )
        db.add(revision)
        db.flush()

    asset.current_revision = max(int(asset.current_revision or 0), revision_number)
    if asset.status != "tombstoned":
        asset.status = "active"
    return AssetProjectionResult(asset, revision, asset_created, revision_created)


def project_document_text_artifact(
    db: Session,
    *,
    document: Any,
    content: str,
    provider: str,
    provider_version: str,
    metadata: dict[str, Any] | None = None,
) -> DerivedArtifact:
    """Dual-write parsed document text as a canonical derived artifact."""

    projection = project_document(db, document)
    if projection.revision is None:
        raise AssetProjectionConflict(
            "cannot create derived artifact before the source revision is immutable"
        )
    parse_artifact = dict((metadata or {}).get("parse_artifact") or {})
    confidence_value = parse_artifact.get("confidence")
    confidence = (
        float(confidence_value) if isinstance(confidence_value, (int, float)) else None
    )
    asset_kind = projection.asset.asset_kind
    parse_chunks = parse_artifact.get("chunks") or [
        {"text": content, "section": "document", "chunk_index": 0}
    ]
    inferred_locator_fallback = asset_kind == "image" and any(
        not dict(raw_chunk or {}).get("bbox")
        or bool(dict(raw_chunk or {}).get("locator_fallback"))
        for raw_chunk in parse_chunks
    )
    quality_state = document_quality_state(
        {
            **dict(metadata or {}),
            "file_extension": (
                "." + str(getattr(document, "file_type", "") or "").lower().lstrip(".")
            ),
            "content_hash": str(
                getattr(document, "content_hash", "") or parse_artifact.get("source_hash") or ""
            ),
            "locator_fallback": bool(
                (metadata or {}).get("locator_fallback")
                or inferred_locator_fallback
            ),
            "quality_score": parse_artifact.get("confidence"),
            **{
                key: value
                for key, value in parse_artifact.items()
                if key in {"quality_score", "ocr_used", "ocr_confidence", "errors"}
            },
        }
    )
    digest = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
    artifact = (
        db.query(DerivedArtifact)
        .filter(
            DerivedArtifact.tenant_id == document.tenant_id,
            DerivedArtifact.asset_revision_id == projection.revision.id,
            DerivedArtifact.artifact_kind == "extracted_text",
            DerivedArtifact.provider == provider,
            DerivedArtifact.provider_version == provider_version,
            DerivedArtifact.content_hash == digest,
        )
        .first()
    )
    if artifact is None:
        artifact = DerivedArtifact(
            tenant_id=document.tenant_id,
            asset_revision_id=projection.revision.id,
            artifact_kind="extracted_text",
            content_hash=digest,
            provider=provider,
            provider_version=provider_version,
            quality_state=quality_state,
            confidence=confidence,
            content=content,
            metadata_json={
                **dict(metadata or {}),
                "legacy_document_id": str(document.id),
                "legacy_document_revision": int(document.version or 1),
            },
        )
        db.add(artifact)
        db.flush()
    else:
        artifact.quality_state = quality_state
        artifact.confidence = confidence

    for index, raw_chunk in enumerate(parse_chunks):
        chunk = dict(raw_chunk or {})
        chunk_content = str(chunk.get("text") or "").strip()
        if not chunk_content:
            continue
        if asset_kind == "spreadsheet":
            artifact_kind = "table"
            locator_kind = "table"
        elif asset_kind == "image":
            artifact_kind = "ocr_region"
            locator_kind = "image"
        else:
            artifact_kind = "layout_page"
            locator_kind = "document"
        chunk_digest = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()
        child = (
            db.query(DerivedArtifact)
            .filter(
                DerivedArtifact.tenant_id == document.tenant_id,
                DerivedArtifact.asset_revision_id == projection.revision.id,
                DerivedArtifact.artifact_kind == artifact_kind,
                DerivedArtifact.provider == provider,
                DerivedArtifact.provider_version == provider_version,
                DerivedArtifact.content_hash == chunk_digest,
            )
            .first()
        )
        if child is None:
            child = DerivedArtifact(
                tenant_id=document.tenant_id,
                asset_revision_id=projection.revision.id,
                artifact_kind=artifact_kind,
                content_hash=chunk_digest,
                provider=provider,
                provider_version=provider_version,
                quality_state=quality_state,
                confidence=confidence,
                content=chunk_content,
                metadata_json={
                    "parse_chunk_index": int(chunk.get("chunk_index", index)),
                    "legacy_document_id": str(document.id),
                    "legacy_document_revision": int(document.version or 1),
                },
            )
            db.add(child)
            db.flush()
        else:
            child.quality_state = quality_state
            child.confidence = confidence

        hierarchy = [
            str(item).strip()
            for item in chunk.get("hierarchy") or []
            if str(item).strip()
        ]
        bbox = chunk.get("bbox")
        if isinstance(bbox, dict):
            bbox = [
                bbox.get("x", 0),
                bbox.get("y", 0),
                bbox.get("w", 0),
                bbox.get("h", 0),
            ]
        locator_values: dict[str, Any] = {
            "page": chunk.get("page"),
            "section": chunk.get("section") or (hierarchy[-1] if hierarchy else None),
            "section_path": hierarchy,
            "paragraph_index": chunk.get("paragraph_index"),
            "slide_number": chunk.get("slide_number"),
            "bbox": bbox,
            "coordinate_space": "normalized" if bbox is not None else None,
            "locator_fallback": bool(chunk.get("locator_fallback", False)),
            "worksheet": chunk.get("worksheet"),
            "table_name": chunk.get("table_name"),
            "row_number": chunk.get("row_number"),
            "column_name": chunk.get("column_name"),
            "cell_range": chunk.get("cell_range"),
        }
        if locator_kind == "document" and not (
            locator_values["page"] or locator_values["section"]
        ):
            locator_values["section"] = "document"
        if locator_kind == "table" and not (
            locator_values["worksheet"] or locator_values["table_name"]
        ):
            locator_values["table_name"] = document.filename.rsplit(".", 1)[0]
        if locator_kind == "table" and not any(
            locator_values[key] for key in ("row_number", "column_name", "cell_range")
        ):
            locator_values["row_number"] = 1
        if locator_kind == "image" and locator_values["bbox"] is None:
            locator_values["bbox"] = [0.0, 0.0, 1.0, 1.0]
            locator_values["coordinate_space"] = "normalized"
            locator_values["locator_fallback"] = True
        existing_spans = (
            db.query(EvidenceSpan)
            .filter(
                EvidenceSpan.tenant_id == document.tenant_id,
                EvidenceSpan.artifact_id == child.id,
                EvidenceSpan.asset_revision_id == projection.revision.id,
            )
            .all()
        )
        comparable_keys = (
            "page",
            "section",
            "section_path",
            "paragraph_index",
            "slide_number",
            "bbox",
            "coordinate_space",
            "locator_fallback",
            "worksheet",
            "table_name",
            "row_number",
            "column_name",
            "cell_range",
        )
        exists = any(
            span.locator_kind == locator_kind
            and all(
                getattr(span, key) == locator_values.get(key) for key in comparable_keys
            )
            for span in existing_spans
        )
        if not exists:
            db.add(
                EvidenceSpan(
                    tenant_id=document.tenant_id,
                    artifact_id=child.id,
                    asset_revision_id=projection.revision.id,
                    locator_kind=locator_kind,
                    **{
                        key: value
                        for key, value in locator_values.items()
                        if value is not None
                    },
                )
            )
    db.flush()
    return artifact


def ensure_capture_asset(db: Session, capture: Any) -> SourceAsset:
    """Create the stable audio asset identity for a long capture session."""

    if getattr(capture, "source_asset_id", None):
        asset = (
            db.query(SourceAsset)
            .filter(
                SourceAsset.tenant_id == capture.tenant_id,
                SourceAsset.id == capture.source_asset_id,
            )
            .first()
        )
        if asset is None:
            raise AssetProjectionConflict("capture references a missing source asset")
        return asset

    from app.services.asset_visibility import canonical_asset_acl

    capture_metadata = dict(getattr(capture, "transcript_metadata", None) or {}).get(
        "capture", {}
    )
    department_id = capture_metadata.get("department_id")
    visibility = "restricted" if department_id else "private"
    asset = SourceAsset(
        tenant_id=capture.tenant_id,
        asset_kind="audio",
        title=capture.title,
        source_system="core_capture",
        source_record_id=str(capture.id),
        data_classification=str(
            capture_metadata.get("data_classification") or "confidential"
        ),
        acl_reference={
            **canonical_asset_acl(
                owner_subject_id=capture.owner_id,
                visibility=visibility,
                allowed_department_ids=[department_id] if department_id else None,
            ),
            "consent_version": capture.consent_version,
        },
        metadata_json={
            "direct_intake": True,
            "capture_session_id": str(capture.id),
            "equipment_id": capture.equipment_id,
            "source_module": capture_metadata.get("source_module") or "core",
            "purpose": capture_metadata.get("purpose") or "knowledge_capture",
            "intake_context": dict(capture_metadata.get("context_metadata") or {}),
        },
        captured_by=capture.owner_id,
        status="pending",
    )
    db.add(asset)
    db.flush()
    capture.source_asset_id = asset.id
    return asset


def finalize_capture_asset_revision(
    db: Session,
    *,
    capture: Any,
    chunks: Iterable[Any],
) -> AssetRevision:
    """Persist an immutable manifest revision for a completed chunked recording."""

    asset = ensure_capture_asset(db, capture)
    ordered = sorted(chunks, key=lambda chunk: int(chunk.sequence))
    manifest = [
        {
            "sequence": int(chunk.sequence),
            "offset_ms": int(chunk.offset_ms or 0),
            "duration_ms": int(chunk.duration_ms or 0),
            "storage_key": str(chunk.storage_key),
            "media_type": str(chunk.mime_type),
            "size_bytes": int(chunk.size_bytes),
            "sha256": str(chunk.sha256).lower(),
        }
        for chunk in ordered
    ]
    serialized = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    revision_number = 1

    revision = (
        db.query(AssetRevision)
        .filter(
            AssetRevision.tenant_id == capture.tenant_id,
            AssetRevision.asset_id == asset.id,
            AssetRevision.revision == revision_number,
        )
        .first()
    )
    if revision is not None:
        if revision.content_hash != digest:
            raise AssetProjectionConflict(
                "capture manifest conflicts with immutable asset revision"
            )
    else:
        revision = AssetRevision(
            tenant_id=capture.tenant_id,
            asset_id=asset.id,
            revision=revision_number,
            media_type="application/vnd.enclave.audio-manifest+json",
            content_uri=f"capture://{capture.id}/revisions/{revision_number}",
            content_hash=digest,
            byte_size=sum(item["size_bytes"] for item in manifest),
            duration_ms=int(capture.total_duration_ms or 0),
            ingestion_status="ready",
            retention_policy=dict(capture.audio_policy_snapshot or {}),
            metadata_json={"chunks": manifest, "chunk_count": len(manifest)},
            created_by=capture.owner_id,
        )
        db.add(revision)
        db.flush()

    capture.source_asset_id = asset.id
    capture.source_asset_revision_id = revision.id
    asset.current_revision = revision_number
    asset.status = "active"
    return revision


def project_capture_transcript_segments(
    db: Session,
    *,
    capture: Any,
    segments: Iterable[Any],
    provider: str,
    provider_version: str,
) -> list[DerivedArtifact]:
    """Project timestamped transcript segments with exact audio evidence."""

    if not getattr(capture, "source_asset_revision_id", None):
        raise AssetProjectionConflict("capture has no immutable source revision")
    artifacts: list[DerivedArtifact] = []
    for segment in segments:
        text = str(segment.corrected_text or segment.raw_text or "").strip()
        if not text:
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        artifact = (
            db.query(DerivedArtifact)
            .filter(
                DerivedArtifact.tenant_id == capture.tenant_id,
                DerivedArtifact.asset_revision_id == capture.source_asset_revision_id,
                DerivedArtifact.artifact_kind == "transcript_segment",
                DerivedArtifact.provider == provider,
                DerivedArtifact.provider_version == provider_version,
                DerivedArtifact.content_hash == digest,
            )
            .first()
        )
        if artifact is None:
            artifact = DerivedArtifact(
                tenant_id=capture.tenant_id,
                asset_revision_id=capture.source_asset_revision_id,
                artifact_kind="transcript_segment",
                content_hash=digest,
                provider=provider,
                provider_version=provider_version,
                quality_state="review_required",
                content=text,
                metadata_json={
                    "capture_session_id": str(capture.id),
                    "legacy_segment_id": str(segment.id),
                    "sequence": int(segment.sequence),
                },
            )
            db.add(artifact)
            db.flush()
        start_ms = max(0, int(segment.start_ms))
        end_ms = max(start_ms + 1, int(segment.end_ms))
        existing_span = (
            db.query(EvidenceSpan.id)
            .filter(
                EvidenceSpan.tenant_id == capture.tenant_id,
                EvidenceSpan.artifact_id == artifact.id,
                EvidenceSpan.asset_revision_id == capture.source_asset_revision_id,
                EvidenceSpan.locator_kind == "audio",
                EvidenceSpan.start_ms == start_ms,
                EvidenceSpan.end_ms == end_ms,
            )
            .first()
        )
        if existing_span is None:
            db.add(
                EvidenceSpan(
                    tenant_id=capture.tenant_id,
                    artifact_id=artifact.id,
                    asset_revision_id=capture.source_asset_revision_id,
                    locator_kind="audio",
                    start_ms=start_ms,
                    end_ms=end_ms,
                    speaker=segment.speaker,
                )
            )
        artifacts.append(artifact)
    db.flush()
    return artifacts


def backfill_document_assets(
    db: Session,
    *,
    tenant_id: UUID,
    limit: int = 500,
) -> dict[str, int]:
    """Project legacy documents in bounded, resumable batches without commit."""

    from app.models.document import Document

    rows = (
        db.query(Document)
        .filter(
            Document.tenant_id == tenant_id,
            Document.source_asset_id.is_(None),
        )
        .order_by(Document.created_at.asc(), Document.id.asc())
        .limit(max(1, min(int(limit), 5000)))
        .all()
    )
    assets = 0
    revisions = 0
    pending = 0
    for document in rows:
        result = project_document(db, document)
        assets += int(result.asset_created)
        revisions += int(result.revision_created)
        pending += int(result.revision is None)
    db.flush()
    return {
        "documents_scanned": len(rows),
        "assets_created": assets,
        "revisions_created": revisions,
        "pending_source_bytes": pending,
    }


def mark_capture_audio_purged(db: Session, *, capture: Any) -> bool:
    """Mark source bytes unavailable while preserving immutable lineage."""

    revision_id = getattr(capture, "source_asset_revision_id", None)
    if not revision_id:
        return False
    revision = (
        db.query(AssetRevision)
        .filter(
            AssetRevision.tenant_id == capture.tenant_id,
            AssetRevision.id == revision_id,
        )
        .first()
    )
    if revision is None:
        raise AssetProjectionConflict("capture source revision is missing")
    revision.ingestion_status = "purged"
    return True
