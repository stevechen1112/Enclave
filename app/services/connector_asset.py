"""Canonical-first materialization for connector resources."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, SourceAsset
from app.services.asset_projection import infer_asset_kind, normalize_sha256


def materialize_connector_asset(
    db: Session,
    *,
    tenant_id: UUID,
    source_system: str,
    resource: dict[str, Any],
    content_uri: str,
    byte_size: int,
    created_by: UUID | None,
) -> tuple[SourceAsset, AssetRevision]:
    record_id = str(resource["source_record_id"])
    digest = normalize_sha256(resource.get("content_hash"))
    if digest is None:
        raise ValueError("connector_resource_missing_sha256")
    asset = (
        db.query(SourceAsset)
        .filter(
            SourceAsset.tenant_id == tenant_id,
            SourceAsset.source_system == source_system,
            SourceAsset.source_record_id == record_id,
            SourceAsset.tombstoned_at.is_(None),
        )
        .first()
    )
    if asset is None:
        suffix = Path(resource.get("title") or content_uri).suffix.lstrip(".")
        asset = SourceAsset(
            tenant_id=tenant_id,
            asset_kind=infer_asset_kind(
                filename=str(resource.get("title") or record_id), file_type=suffix
            ),
            title=str(resource.get("title") or record_id),
            source_system=source_system,
            source_record_id=record_id,
            data_classification=str(resource.get("data_classification") or "internal"),
            acl_reference={
                "policy": "source_acl",
                "source_system": source_system,
                "source_record_id": record_id,
                "default": "deny",
            },
            metadata_json={
                **dict(resource.get("metadata") or {}),
                "connector_canonical_first": True,
            },
            created_by=created_by,
            status="pending",
        )
        db.add(asset)
        db.flush()
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
    if current and current.content_hash == digest:
        return asset, current
    revision = AssetRevision(
        tenant_id=tenant_id,
        asset_id=asset.id,
        revision=int(asset.current_revision or 0) + 1,
        media_type=str(resource.get("mime_type") or "application/octet-stream"),
        content_uri=content_uri,
        content_hash=digest,
        external_version=resource.get("source_version"),
        byte_size=byte_size,
        ingestion_status="pending",
        metadata_json={"connector_resource": True},
        supersedes_revision_id=current.id if current else None,
        created_by=created_by,
    )
    db.add(revision)
    db.flush()
    asset.current_revision = revision.revision
    asset.status = "active"
    return asset, revision
