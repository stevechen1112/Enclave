"""Resolve user-visible active KB revisions before any retrieval arm runs."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from app.config import settings
from app.db.session import SessionLocal
from app.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseRevision,
)


def _can_access(kb: KnowledgeBase, authz) -> bool:
    if authz.is_superuser or authz.has_kb_admin:
        return True
    members = list(kb.members or [])
    if not members:
        return True  # backward-compatible tenant-wide KB until a membership policy is configured
    subjects = {
        "user": {authz.subject_id},
        "department": set(authz.department_ids),
        "group": set(authz.group_ids),
    }
    matching = [
        m for m in members if m.subject_id in subjects.get(m.subject_type, set())
    ]
    if any(m.effect == "deny" for m in matching):
        return False
    return any(m.effect == "allow" for m in matching)


def resolve_kb_revision_scope(
    *, authz, requested: Optional[dict[str, Any]], db=None
) -> dict[str, Any]:
    scope = dict(requested or {})
    caller_selected_scope = bool(
        scope.get("kb_revision_id") or scope.get("kb_revision_ids")
    )
    raw_ids = []
    if scope.get("kb_revision_id"):
        raw_ids.append(scope["kb_revision_id"])
    raw_ids.extend(scope.get("kb_revision_ids") or [])
    requested_ids = set()
    for value in raw_ids:
        try:
            requested_ids.add(UUID(str(value)))
        except (TypeError, ValueError):
            scope.pop("kb_revision_id", None)
            scope["kb_revision_ids"] = []
            scope["include_tenant_knowledge_units"] = False
            return scope

    own = db is None
    session = db or SessionLocal()
    try:
        from app.services.rls import apply_rls_context

        apply_rls_context(session, authz.tenant_id)
        base_query = (
            session.query(KnowledgeBaseRevision)
            .join(KnowledgeBase)
            .filter(
                KnowledgeBase.tenant_id == authz.tenant_id,
                KnowledgeBase.status == "active",
            )
        )
        if requested_ids:
            query = base_query.filter(KnowledgeBaseRevision.id.in_(requested_ids))
            # Candidate/shadow revisions are an administrative test surface,
            # never an ordinary reader escape hatch.
            if not (authz.is_superuser or authz.has_kb_admin):
                query = query.filter(KnowledgeBaseRevision.status == "active")
        else:
            query = base_query.filter(KnowledgeBaseRevision.status == "active")
        candidates = query.all()
        allowed = [
            revision.id for revision in candidates if _can_access(revision.kb, authz)
        ]
    finally:
        if own:
            session.close()

    scope.pop("kb_revision_id", None)
    if (
        not requested_ids
        and not candidates
        and settings.KNOWLEDGE_UNIT_READ_MODE == "shadow"
    ):
        # Shadow is the deliberate compatibility period while a tenant has
        # not yet published its first immutable KB revision.  Returning an
        # explicit empty list here silently disabled the legacy read path even
        # though readiness correctly reported completed documents as usable.
        # Once any active revision exists, membership denial must still remain
        # explicit and fail closed; enforce mode always remains fail closed.
        scope.pop("kb_revision_ids", None)
        return scope
    scope["kb_revision_ids"] = [str(value) for value in sorted(allowed, key=str)]
    # An ordinary tenant-wide Ask session searches both the tenant's active KB
    # revisions and reviewed source units (audio/video/image extracts) that are
    # published to the tenant release.  A caller-selected KB remains strict and
    # must never be widened silently.
    scope["include_tenant_knowledge_units"] = not caller_selected_scope
    # No active revision is not a legacy-search escape hatch. Processing a
    # document and publishing knowledge are separate states; an empty active
    # scope must therefore remain explicit and fail closed in every reader.
    return scope
