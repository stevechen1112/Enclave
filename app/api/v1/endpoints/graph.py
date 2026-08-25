"""Phase 4 — Graph query API. API-only; no production write path (DD-M09A)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.product_surface import (
    GRAPH_PRODUCT_STATUS,
    apply_product_status_headers,
    with_runtime_status,
)
from app.core.authorization import AuthorizationContext
from app.models.user import User
from app.services.graph_service import GraphService

router = APIRouter(
    prefix="/graph",
    tags=["graph (API-only; no production write)"],
)
_graph = GraphService()


def _graph_headers(response: Response) -> None:
    apply_product_status_headers(response, with_runtime_status(GRAPH_PRODUCT_STATUS))


class GraphTraverseRequest(BaseModel):
    start_entity_id: UUID
    depth: int = Field(default=2, ge=1, le=5)
    namespace: str = "weknora"


@router.get("/product-status")
def graph_product_status(
    response: Response,
    current_user: User = Depends(deps.get_current_active_user),
) -> Dict[str, Any]:
    """Honest product surface notice — no Web UI, no production write path."""
    _ = current_user
    status = with_runtime_status(GRAPH_PRODUCT_STATUS)
    apply_product_status_headers(response, status)
    return status


@router.get("/search")
def search_entities(
    response: Response,
    q: str = Query(..., min_length=1),
    namespace: Optional[str] = None,
    limit: int = Query(default=20, le=50),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> List[Dict[str, Any]]:
    _graph_headers(response)
    authz = AuthorizationContext.from_user(current_user)
    return _graph.search_entities(
        db, current_user.tenant_id, q, authz, namespace=namespace, limit=limit,
    )


@router.post("/traverse")
def traverse_graph(
    body: GraphTraverseRequest,
    response: Response,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Dict[str, Any]:
    _graph_headers(response)
    authz = AuthorizationContext.from_user(current_user)
    return _graph.traverse(
        db,
        current_user.tenant_id,
        body.start_entity_id,
        authz,
        depth=body.depth,
        namespace=body.namespace,
    )


@router.get("/entities/{entity_id}")
def get_entity(
    entity_id: UUID,
    response: Response,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Dict[str, Any]:
    _graph_headers(response)
    from app.models.graph import GraphEntity
    authz = AuthorizationContext.from_user(current_user)
    entity = db.query(GraphEntity).filter(
        GraphEntity.id == entity_id,
        GraphEntity.tenant_id == current_user.tenant_id,
    ).first()
    if not entity or not _graph._entity_allowed(entity, authz, db=db):
        raise HTTPException(status_code=404, detail="實體不存在或無權限")
    payload = {
        "id": str(entity.id),
        "name": entity.name,
        "entity_type": entity.entity_type,
        "namespace": entity.namespace,
        "source_document_id": str(entity.source_document_id) if entity.source_document_id else None,
        "product_notice": GRAPH_PRODUCT_STATUS,
    }
    return payload
