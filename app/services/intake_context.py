"""Validation and persistence helpers shared by all Input intake routes."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
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


def acquire_content_identity_lock(
    db: Session, *, tenant_id: UUID, content_hash: str
) -> None:
    """Serialize same-tenant, same-content intake until the transaction ends.

    The read-before-create duplicate check is otherwise racy when a user submits
    the same file twice from separate browser requests. PostgreSQL advisory
    transaction locks avoid a schema-wide uniqueness rule, which would wrongly
    merge assets that intentionally use different ACL or intake context.
    """

    if db.get_bind().dialect.name != "postgresql":
        return
    identity = f"{tenant_id}:{content_hash.lower()}".encode("utf-8")
    lock_key = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


def find_matching_content_asset(
    db: Session,
    *,
    current_user: Any,
    content_hash: str,
    asset_kind: str,
    department_id: UUID | None,
    data_classification: str,
    context: dict[str, Any] | None,
) -> SourceAsset | None:
    """Return an accessible active upload with identical bytes and policy.

    Content equality alone is insufficient: the same bytes may deliberately be
    imported under a different department, classification or operational
    context. Those remain distinct logical assets.
    """

    hashes = {content_hash.lower()}
    if not content_hash.lower().startswith("sha256:"):
        hashes.add(f"sha256:{content_hash.lower()}")
    candidates = (
        db.query(SourceAsset)
        .join(
            AssetRevision,
            (AssetRevision.tenant_id == SourceAsset.tenant_id)
            & (AssetRevision.asset_id == SourceAsset.id)
            & (AssetRevision.revision == SourceAsset.current_revision),
        )
        .filter(
            SourceAsset.tenant_id == current_user.tenant_id,
            SourceAsset.asset_kind == asset_kind,
            SourceAsset.source_system == "upload",
            SourceAsset.tombstoned_at.is_(None),
            SourceAsset.data_classification == data_classification,
            AssetRevision.content_hash.in_(hashes),
        )
        .order_by(SourceAsset.created_at.desc())
        .all()
    )
    expected_departments = {str(department_id)} if department_id else set()
    expected_context = dict(context or {})
    from app.core.authorization import AuthorizationContext
    from app.services.asset_visibility import asset_access_allows

    for asset in candidates:
        acl = dict(asset.acl_reference or {})
        actual_departments = {
            str(value) for value in (acl.get("allowed_department_ids") or [])
        }
        actual_context = dict((asset.metadata_json or {}).get("intake_context") or {})
        if (
            actual_departments != expected_departments
            or actual_context != expected_context
        ):
            continue
        if asset_access_allows(
            db, asset, authz=AuthorizationContext.from_user(current_user)
        ):
            return asset
    return None


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
                    raise IntakeContextError(
                        "context_metadata.tags must contain strings"
                    )
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
