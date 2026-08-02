"""Shared document revocation path — tombstone + deny + cache + wiki/graph."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.crud import crud_document
from app.models.document import Document

logger = logging.getLogger(__name__)


class DocumentRevocationService:
    def revoke(
        self,
        db: Session,
        *,
        document_id: UUID,
        actor_id: UUID,
        tenant_id: UUID,
        reason: str = "user_request",
    ) -> Dict[str, Any]:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc or doc.tombstoned_at is not None:
            return {"ok": False, "reason": "not_found_or_already_deleted", "document_id": str(document_id)}
        if doc.tenant_id != tenant_id:
            return {"ok": False, "reason": "tenant_mismatch", "document_id": str(document_id)}

        if not crud_document.tombstone(db, document_id=document_id, reason=reason):
            return {"ok": False, "reason": "tombstone_failed", "document_id": str(document_id)}

        try:
            from app.gateway.authorization import get_gateway_authorizer
            get_gateway_authorizer().deny_resource(
                str(document_id), tenant_id=tenant_id, reason=reason,
            )
        except Exception as exc:
            logger.warning("deny entry after revoke failed: %s", exc)

        try:
            from app.services.kb_retrieval import KnowledgeBaseRetriever
            KnowledgeBaseRetriever().invalidate_cache(tenant_id)
        except Exception as exc:
            logger.warning("invalidate cache after revoke failed: %s", exc)

        wiki_result: Optional[Dict[str, int]] = None
        try:
            from app.services.wiki_compiler import WikiCompiler
            wiki_result = WikiCompiler().tombstone_by_source_document(
                db, tenant_id, str(document_id), recompile=True,
            )
        except Exception as exc:
            logger.warning("wiki tombstone after revoke failed: %s", exc)

        graph_result: Optional[Dict[str, int]] = None
        try:
            from app.services.graph_service import GraphService
            graph_result = GraphService().tombstone_by_source_document(
                db, tenant_id, document_id,
            )
        except Exception as exc:
            logger.warning("graph tombstone after revoke failed: %s", exc)

        return {
            "ok": True,
            "document_id": str(document_id),
            "deny_first": True,
            "wiki": wiki_result,
            "graph": graph_result,
        }


_revocation: Optional[DocumentRevocationService] = None


def get_document_revocation() -> DocumentRevocationService:
    global _revocation
    if _revocation is None:
        _revocation = DocumentRevocationService()
    return _revocation
