"""Canonical visibility PEP for SourceAsset and provider candidates."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models.asset import SourceAsset
from app.platform.assets.access import AssetAccessPolicy

logger = logging.getLogger(__name__)


def asset_access_allows(
    db: Session,
    asset: SourceAsset,
    *,
    authz: AuthorizationContext,
) -> bool:
    """Deny-first visibility check including connector source ACL.

    Malformed policy data and connector ACL lookup failures fail closed. Tenant
    A documented KB administrator may bypass a missing allow, but never an
    explicit deny, tenant mismatch or lifecycle restriction.
    """

    if asset.tenant_id != authz.tenant_id or asset.tombstoned_at is not None:
        return False
    try:
        policy = AssetAccessPolicy.from_mapping(asset.acl_reference)
        if not policy.allows(authz):
            return False
        if asset.source_system == "upload" or bool(
            (asset.metadata_json or {}).get("direct_intake")
        ):
            return True
        return _external_source_acl_allows(db, asset=asset, authz=authz)
    except Exception:
        logger.exception("asset visibility evaluation failed closed: %s", asset.id)
        return False


def _external_source_acl_allows(
    db: Session,
    *,
    asset: SourceAsset,
    authz: AuthorizationContext,
) -> bool:
    if not asset.source_record_id:
        return False

    from app.models.connector import ExternalPrincipal, SourceAclEntry

    subject_ids = {authz.subject_id, *authz.department_ids, *authz.group_ids}
    principal_ids = [
        row[0]
        for row in db.query(ExternalPrincipal.id).filter(
            ExternalPrincipal.tenant_id == authz.tenant_id,
            ExternalPrincipal.mapped_subject_id.in_(subject_ids),
        )
    ]
    if not principal_ids:
        return authz.has_kb_admin
    entries = (
        db.query(SourceAclEntry.effect)
        .filter(
            SourceAclEntry.tenant_id == authz.tenant_id,
            SourceAclEntry.source_record_id == asset.source_record_id,
            SourceAclEntry.principal_id.in_(principal_ids),
            SourceAclEntry.permission.in_(["read", "write", "admin"]),
        )
        .all()
    )
    effects = {str(row[0] or "").lower() for row in entries}
    if "deny" in effects:
        return False
    return "allow" in effects or authz.has_kb_admin


def require_asset_access(
    db: Session,
    asset: SourceAsset,
    *,
    authz: AuthorizationContext,
) -> SourceAsset:
    if not asset_access_allows(db, asset, authz=authz):
        raise LookupError("asset is not visible")
    return asset


def canonical_asset_acl(
    *,
    owner_subject_id: Any,
    visibility: str = "tenant",
    allowed_department_ids: list[Any] | None = None,
) -> dict[str, Any]:
    return dict(
        AssetAccessPolicy(
            visibility=visibility,
            owner_subject_id=(
                str(owner_subject_id) if owner_subject_id is not None else None
            ),
            allowed_department_ids=frozenset(
                str(item) for item in (allowed_department_ids or []) if item
            ),
        ).to_mapping()
    )


def candidate_asset_access_allows(
    db: Session | None,
    *,
    tenant_id: Any,
    metadata: Any,
    authz: AuthorizationContext,
) -> bool:
    """Registry-boundary revalidation for candidates carrying an asset id."""
    if str(tenant_id) != str(authz.tenant_id):
        return False
    raw = dict(metadata or {})
    asset_id = raw.get("source_asset_id") or raw.get("asset_id")
    if not asset_id:
        return True
    if db is None:
        return False
    try:
        parsed_id = UUID(str(asset_id))
    except (TypeError, ValueError, AttributeError):
        return False
    asset = (
        db.query(SourceAsset)
        .filter(
            SourceAsset.tenant_id == authz.tenant_id,
            SourceAsset.id == parsed_id,
        )
        .first()
    )
    return bool(asset and asset_access_allows(db, asset, authz=authz))
