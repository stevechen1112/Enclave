"""Shared document visibility predicates for every retrieval arm.

The knowledge runtime has several physical readers (chunks, catalog, compiled
artifacts and PageIndex).  Keeping tenant/department/source ACL logic here
prevents a secondary arm from becoming an authorization bypass.
"""
from __future__ import annotations

from sqlalchemy import and_, or_

from app.models.connector import ExternalPrincipal, SourceAclEntry
from app.models.document import Document


def apply_document_visibility(query_obj, *, authz, db, require_completed: bool = True):
    """Apply the common pre-retrieval PEP to a query containing ``Document``."""
    query_obj = query_obj.filter(
        Document.tenant_id == authz.tenant_id,
        Document.tombstoned_at.is_(None),
    )
    if require_completed:
        query_obj = query_obj.filter(Document.status == "completed")
    if authz.has_kb_admin:
        return query_obj

    departments = authz.department_filter_ids()
    if departments:
        query_obj = query_obj.filter(
            or_(Document.department_id.is_(None), Document.department_id.in_(departments))
        )
    else:
        query_obj = query_obj.filter(Document.department_id.is_(None))

    principal_ids = [
        row[0]
        for row in db.query(ExternalPrincipal.id).filter(
            ExternalPrincipal.tenant_id == authz.tenant_id,
            ExternalPrincipal.mapped_subject_id == authz.subject_id,
        )
    ]
    if not principal_ids:
        return query_obj.filter(Document.source_system.is_(None))

    allow_exists = (
        db.query(SourceAclEntry.id)
        .filter(
            SourceAclEntry.tenant_id == authz.tenant_id,
            SourceAclEntry.source_record_id == Document.source_record_id,
            SourceAclEntry.principal_id.in_(principal_ids),
            SourceAclEntry.effect == "allow",
        )
        .correlate(Document)
        .exists()
    )
    deny_exists = (
        db.query(SourceAclEntry.id)
        .filter(
            SourceAclEntry.tenant_id == authz.tenant_id,
            SourceAclEntry.source_record_id == Document.source_record_id,
            SourceAclEntry.principal_id.in_(principal_ids),
            SourceAclEntry.effect == "deny",
        )
        .correlate(Document)
        .exists()
    )
    return query_obj.filter(
        or_(
            Document.source_system.is_(None),
            and_(Document.source_record_id.isnot(None), allow_exists, ~deny_exists),
        )
    )


def deny_set_allows(document_id, *, authz) -> bool:
    """Apply the runtime deny-set; lookup failures are deliberately closed."""
    try:
        from app.gateway.authorization import get_gateway_authorizer

        return not get_gateway_authorizer().is_denied(str(document_id), authz.subject_id)
    except Exception:
        return False
