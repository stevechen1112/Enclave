"""Persistent policy deny store."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.policy_deny import PolicyDenyEntry

# Sentinel subject: resource-wide deny applies to every subject (deny-first revoke).
RESOURCE_WIDE_DENY_SUBJECT = UUID(int=0)


def add_deny(
    db: Session,
    tenant_id: UUID,
    resource_type: str,
    resource_id: str,
    subject_id: UUID,
    reason: str = "",
) -> PolicyDenyEntry:
    existing = (
        db.query(PolicyDenyEntry)
        .filter(
            PolicyDenyEntry.resource_type == resource_type,
            PolicyDenyEntry.resource_id == resource_id,
            PolicyDenyEntry.subject_id == subject_id,
        )
        .first()
    )
    if existing:
        return existing
    row = PolicyDenyEntry(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        subject_id=subject_id,
        reason=reason,
    )
    db.add(row)
    db.flush()
    return row


def add_resource_deny(
    db: Session,
    tenant_id: UUID,
    resource_type: str,
    resource_id: str,
    reason: str = "revoked",
) -> PolicyDenyEntry:
    """Deny all subjects for a resource until cleared."""
    return add_deny(
        db, tenant_id, resource_type, resource_id, RESOURCE_WIDE_DENY_SUBJECT, reason=reason,
    )


def is_denied(
    db: Session,
    resource_type: str,
    resource_id: str,
    subject_id: UUID,
) -> bool:
    now = datetime.now(timezone.utc)
    row = (
        db.query(PolicyDenyEntry)
        .filter(
            PolicyDenyEntry.resource_type == resource_type,
            PolicyDenyEntry.resource_id == resource_id,
            or_(
                PolicyDenyEntry.subject_id == subject_id,
                PolicyDenyEntry.subject_id == RESOURCE_WIDE_DENY_SUBJECT,
            ),
        )
        .first()
    )
    if not row:
        return False
    if row.expires_at and row.expires_at < now:
        return False
    return True


def remove_deny(
    db: Session,
    resource_type: str,
    resource_id: str,
    subject_id: UUID,
) -> int:
    count = (
        db.query(PolicyDenyEntry)
        .filter(
            PolicyDenyEntry.resource_type == resource_type,
            PolicyDenyEntry.resource_id == resource_id,
            PolicyDenyEntry.subject_id == subject_id,
        )
        .delete()
    )
    db.flush()
    return count


def clear_resource_denies(
    db: Session,
    resource_type: str,
    resource_id: str,
) -> int:
    """Remove all deny rows for a resource (subject-specific + resource-wide)."""
    count = (
        db.query(PolicyDenyEntry)
        .filter(
            PolicyDenyEntry.resource_type == resource_type,
            PolicyDenyEntry.resource_id == resource_id,
        )
        .delete()
    )
    db.flush()
    return count
