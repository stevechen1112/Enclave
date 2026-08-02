"""
Unified Resource PEP — single authorization entry for knowledge reads.

Deny precedence (ADR-004):
  ALLOW = tenant_match
          AND not_tombstoned
          AND not_in_deny_set
          AND department_policy_allows
          AND source_acl_allows_if_connector
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models.document import Document, DocumentChunk
from app.models.connector import ExternalPrincipal, SourceAclEntry

logger = logging.getLogger(__name__)


class ResourcePolicyService:
    """Canonical Policy Enforcement Point for document / connector resources."""

    def authorize_document(
        self,
        db: Session,
        authz: AuthorizationContext,
        document: Document,
        *,
        require_content_access: bool = True,
    ) -> bool:
        if document.tenant_id != authz.tenant_id:
            return False
        if document.tombstoned_at is not None:
            return False
        if self.is_denied(db, authz, str(document.id)):
            return False
        if not authz.can_access_document(document.tenant_id, document.department_id):
            return False
        if require_content_access and document.source_system and document.source_record_id:
            return self.authorize_source_record(
                db,
                authz,
                source_system=document.source_system,
                source_record_id=document.source_record_id,
            )
        return True

    def authorize_source_record(
        self,
        db: Session,
        authz: AuthorizationContext,
        *,
        source_system: Optional[str],
        source_record_id: Optional[str],
    ) -> bool:
        """Object-level connector ACL. Missing IDs → fail closed."""
        if authz.has_kb_admin:
            return True
        if not source_system or not source_record_id:
            return False
        try:
            principals = (
                db.query(ExternalPrincipal)
                .filter(
                    ExternalPrincipal.tenant_id == authz.tenant_id,
                    ExternalPrincipal.mapped_subject_id == authz.subject_id,
                )
                .all()
            )
            if not principals:
                return False
            principal_ids = [p.id for p in principals]
            deny = (
                db.query(SourceAclEntry.id)
                .filter(
                    SourceAclEntry.tenant_id == authz.tenant_id,
                    SourceAclEntry.source_record_id == source_record_id,
                    SourceAclEntry.principal_id.in_(principal_ids),
                    SourceAclEntry.effect == "deny",
                )
                .first()
            )
            if deny:
                return False
            allow = (
                db.query(SourceAclEntry.id)
                .filter(
                    SourceAclEntry.tenant_id == authz.tenant_id,
                    SourceAclEntry.source_record_id == source_record_id,
                    SourceAclEntry.principal_id.in_(principal_ids),
                    SourceAclEntry.effect == "allow",
                )
                .first()
            )
            return allow is not None
        except Exception as exc:
            logger.warning("source ACL lookup failed, deny: %s", exc)
            return False

    def is_denied(self, db: Session, authz: AuthorizationContext, document_id: str) -> bool:
        try:
            from app.gateway.authorization import get_gateway_authorizer
            return get_gateway_authorizer().is_denied(document_id, authz.subject_id)
        except Exception as exc:
            logger.warning("deny-set lookup failed, fail closed: %s", exc)
            return True

    def load_authorized_document(
        self,
        db: Session,
        authz: AuthorizationContext,
        document_id: UUID,
    ) -> Optional[Document]:
        doc = (
            db.query(Document)
            .filter(
                Document.id == document_id,
                Document.tenant_id == authz.tenant_id,
            )
            .first()
        )
        if not doc or not self.authorize_document(db, authz, doc):
            return None
        return doc

    def load_authorized_document_text(
        self,
        db: Session,
        authz: AuthorizationContext,
        document_id: UUID,
        *,
        max_chunks: int = 20,
        max_chars: int = 2000,
    ) -> Optional[str]:
        doc = self.load_authorized_document(db, authz, document_id)
        if not doc:
            return None
        chunks = (
            db.query(DocumentChunk.text)
            .filter(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
            .limit(max_chunks)
            .all()
        )
        preview = "\n".join(c.text for c in chunks)[:max_chars]
        return f"【{doc.filename or document_id}】\n{preview}"

    def filter_documents_by_source_ids(
        self,
        db: Session,
        authz: AuthorizationContext,
        source_document_ids: List[str],
    ) -> List[str]:
        """Return only source document IDs the subject may read (intersection)."""
        allowed: List[str] = []
        for raw in source_document_ids or []:
            try:
                doc_id = UUID(str(raw))
            except (ValueError, TypeError):
                continue
            if self.load_authorized_document(db, authz, doc_id) is not None:
                allowed.append(str(doc_id))
        return allowed


_policy: Optional[ResourcePolicyService] = None


def get_resource_policy() -> ResourcePolicyService:
    global _policy
    if _policy is None:
        _policy = ResourcePolicyService()
    return _policy
