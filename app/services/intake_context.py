"""Validation and persistence helpers shared by all Input intake routes."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, SourceAsset
from app.models.ingestion import IngestionJob

MAX_CONTEXT_BYTES = 16 * 1024
MAX_CONTEXT_STRING = 500
MAX_CONTEXT_LIST_ITEMS = 20
ALLOWED_CONTEXT_KEYS = {
    "site",
    "production_line",
    "equipment",
    "product",
    "work_order",
    "shift",
    "tags",
}


class IntakeContextError(ValueError):
    pass


def parse_intake_context(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    if len(raw.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise IntakeContextError("context_metadata exceeds size limit")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IntakeContextError("context_metadata must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise IntakeContextError("context_metadata must be a JSON object")
    unknown = sorted(set(parsed) - ALLOWED_CONTEXT_KEYS)
    if unknown:
        raise IntakeContextError(
            "unsupported context_metadata keys: " + ", ".join(unknown)
        )
    normalized: dict[str, Any] = {}
    for key, value in parsed.items():
        if value is None or value == "":
            continue
        if key == "tags":
            if not isinstance(value, list):
                raise IntakeContextError("context_metadata.tags must be a list")
            tags = []
            for item in value[:MAX_CONTEXT_LIST_ITEMS]:
                if not isinstance(item, str):
                    raise IntakeContextError("context_metadata.tags must contain strings")
                cleaned = item.strip()[:100]
                if cleaned and cleaned not in tags:
                    tags.append(cleaned)
            if tags:
                normalized[key] = tags
            continue
        if not isinstance(value, str):
            raise IntakeContextError(f"context_metadata.{key} must be a string")
        cleaned = value.strip()
        if cleaned:
            normalized[key] = cleaned[:MAX_CONTEXT_STRING]
    return normalized


def apply_intake_metadata(
    asset: SourceAsset,
    *,
    context: dict[str, Any] | None,
    idempotency_key: str | None,
) -> None:
    metadata = dict(asset.metadata_json or {})
    if context:
        metadata["intake_context"] = dict(context)
    if idempotency_key:
        metadata["intake_idempotency_key"] = idempotency_key
    asset.metadata_json = metadata


def find_idempotent_asset(
    db: Session, *, tenant_id: UUID, idempotency_key: str | None
) -> SourceAsset | None:
    if not idempotency_key:
        return None
    job = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.tenant_id == tenant_id,
            IngestionJob.idempotency_key == idempotency_key,
        )
        .first()
    )
    if job is None:
        return None
    revision = (
        db.query(AssetRevision)
        .filter(
            AssetRevision.tenant_id == tenant_id,
            AssetRevision.id == job.asset_revision_id,
        )
        .first()
    )
    if revision is None:
        raise IntakeContextError("idempotency key references a missing revision")
    asset = (
        db.query(SourceAsset)
        .filter(
            SourceAsset.tenant_id == tenant_id,
            SourceAsset.id == revision.asset_id,
            SourceAsset.tombstoned_at.is_(None),
        )
        .first()
    )
    if asset is None:
        raise IntakeContextError("idempotency key references an unavailable asset")
    return asset


def assert_file_replay_matches(
    db: Session, *, asset: SourceAsset, filename: str, byte_size: int | None
) -> None:
    expected_name = str((asset.metadata_json or {}).get("filename") or "")
    if expected_name and expected_name != filename:
        raise IntakeContextError("idempotency key belongs to another file")
    if byte_size is None:
        return
    revision = (
        db.query(AssetRevision)
        .filter(
            AssetRevision.tenant_id == asset.tenant_id,
            AssetRevision.asset_id == asset.id,
            AssetRevision.revision == asset.current_revision,
        )
        .first()
    )
    if revision is not None and revision.byte_size is not None:
        if int(revision.byte_size) != int(byte_size):
            raise IntakeContextError("idempotency key belongs to another file")
