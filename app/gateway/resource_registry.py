"""
Phase 1 — Gateway Resource Registry

Persist and resolve object-level ID mappings between Enclave and providers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.gateway_resource import GatewayResource

logger = logging.getLogger(__name__)


class ResourceRegistry:
    """CRUD for gateway_resources mappings."""

    def upsert_mapping(
        self,
        db: Session,
        tenant_id: UUID,
        enclave_resource_type: str,
        enclave_resource_id: str,
        enclave_revision: int,
        provider: str,
        provider_resource_id: Optional[str] = None,
        provider_resource_type: Optional[str] = None,
        provider_revision: Optional[int] = None,
        checksum: Optional[str] = None,
        provider_instance_id: Optional[str] = None,
        state: str = "active",
    ) -> GatewayResource:
        existing = (
            db.query(GatewayResource)
            .filter(
                GatewayResource.tenant_id == tenant_id,
                GatewayResource.enclave_resource_type == enclave_resource_type,
                GatewayResource.enclave_resource_id == enclave_resource_id,
                GatewayResource.provider == provider,
                GatewayResource.provider_instance_id == provider_instance_id,
            )
            .first()
        )
        if existing:
            existing.enclave_revision = enclave_revision
            existing.provider_resource_id = provider_resource_id
            existing.provider_resource_type = provider_resource_type
            existing.provider_revision = provider_revision or 0
            existing.checksum = checksum
            existing.state = state
            existing.tombstoned_at = None
            db.flush()
            return existing

        row = GatewayResource(
            tenant_id=tenant_id,
            enclave_resource_type=enclave_resource_type,
            enclave_resource_id=enclave_resource_id,
            enclave_revision=enclave_revision,
            provider=provider,
            provider_instance_id=provider_instance_id,
            provider_resource_type=provider_resource_type,
            provider_resource_id=provider_resource_id,
            provider_revision=provider_revision or 0,
            checksum=checksum,
            state=state,
        )
        db.add(row)
        db.flush()
        return row

    def tombstone(
        self,
        db: Session,
        tenant_id: UUID,
        enclave_resource_type: str,
        enclave_resource_id: str,
        provider: Optional[str] = None,
    ) -> int:
        q = db.query(GatewayResource).filter(
            GatewayResource.tenant_id == tenant_id,
            GatewayResource.enclave_resource_type == enclave_resource_type,
            GatewayResource.enclave_resource_id == enclave_resource_id,
        )
        if provider:
            q = q.filter(GatewayResource.provider == provider)
        rows = q.all()
        now = datetime.now(timezone.utc)
        for row in rows:
            row.state = "tombstoned"
            row.tombstoned_at = now
        db.flush()
        return len(rows)

    def get_provider_resource_id(
        self,
        db: Session,
        tenant_id: UUID,
        enclave_resource_type: str,
        enclave_resource_id: str,
        provider: str,
    ) -> Optional[str]:
        row = (
            db.query(GatewayResource)
            .filter(
                GatewayResource.tenant_id == tenant_id,
                GatewayResource.enclave_resource_type == enclave_resource_type,
                GatewayResource.enclave_resource_id == enclave_resource_id,
                GatewayResource.provider == provider,
                GatewayResource.state == "active",
            )
            .first()
        )
        return row.provider_resource_id if row else None

    def list_mappings(
        self,
        db: Session,
        tenant_id: UUID,
        enclave_resource_id: str,
    ) -> list[Dict[str, Any]]:
        rows = (
            db.query(GatewayResource)
            .filter(
                GatewayResource.tenant_id == tenant_id,
                GatewayResource.enclave_resource_id == enclave_resource_id,
            )
            .all()
        )
        return [
            {
                "provider": r.provider,
                "provider_resource_id": r.provider_resource_id,
                "enclave_revision": r.enclave_revision,
                "state": r.state,
            }
            for r in rows
        ]
