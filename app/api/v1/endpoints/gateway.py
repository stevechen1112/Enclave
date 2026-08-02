"""
Phase 1 — Gateway API Endpoint

將 Gateway 接入 FastAPI，提供統一的知識庫搜尋端點。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.core.authorization import AuthorizationContext
from app.gateway.router import GatewayRouter
from app.gateway.runtime import get_configured_gateway_router
from app.gateway.health import GatewayHealthChecker
from app.gateway.contracts import SearchDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gateway", tags=["gateway"])

_health_checker = GatewayHealthChecker()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="搜尋查詢")
    top_k: int = Field(default=20, ge=1, le=100, description="回傳結果數")
    domain: str = Field(default="hybrid", description="搜尋領域")
    scope: Optional[Dict[str, Any]] = Field(
        default=None,
        description="可選 SearchScope：kb_ids / source_systems / document_types",
    )


def _get_gateway() -> GatewayRouter:
    return get_configured_gateway_router()


@router.post("/search")
async def gateway_search(
    *,
    db: Session = Depends(deps.get_db),
    body: SearchRequest,
    current_user: User = Depends(deps.get_current_active_user),
) -> Dict[str, Any]:
    authz = AuthorizationContext.from_user(current_user)

    try:
        search_domain = SearchDomain(body.domain)
    except ValueError:
        search_domain = SearchDomain.HYBRID

    scope = dict(body.scope or {})
    # connector-only domain 必須走來源 ACL；hybrid 則在 router 對 connector 結果後過濾
    if search_domain == SearchDomain.CONNECTOR and "source_systems" not in scope:
        scope["source_systems"] = ["nas_smb", "sharepoint", "google_drive", "local_fs"]

    gateway = _get_gateway()
    response = await gateway.search(
        authz=authz,
        query=body.query,
        domain=search_domain,
        top_k=body.top_k,
        scope=scope or None,
        db=db,
    )

    # Persist audit trail
    if response.audit_trail:
        from app.gateway.audit import GatewayAuditor
        GatewayAuditor().log_operation(
            db=db,
            tenant_id=authz.tenant_id,
            subject_id=authz.subject_id,
            operation="search",
            trail=response.audit_trail,
            correlation_id=response.request_id,
        )
        db.commit()

    return {
        "request_id": response.request_id,
        "status": response.status,
        "results": [
            {
                "id": r.id,
                "content": r.content,
                "score": r.score,
                "document_id": r.document_id,
                "provider": r.provider,
                "result_type": r.result_type,
            }
            for r in response.results
        ],
        "citations": [
            {
                "citation_id": c.citation_id,
                "canonical_document_id": str(c.canonical_document_id),
                "document_revision": c.document_revision,
                "artifact_type": c.artifact_type,
                "provider": c.provider,
                "retrieval_score": c.retrieval_score,
            }
            for c in response.citations
        ],
        "errors": [
            {"code": e.code, "message": e.message, "provider": e.provider}
            for e in response.errors
        ],
        "audit": {
            "providers_called": response.audit_trail.providers_called if response.audit_trail else [],
            "total_latency_ms": response.audit_trail.total_latency_ms if response.audit_trail else 0,
            "decisions": response.audit_trail.decisions if response.audit_trail else [],
        },
    }


@router.get("/health")
async def gateway_health() -> Dict[str, Any]:
    gateway = _get_gateway()
    return await _health_checker.check_adapters(gateway._adapters)
