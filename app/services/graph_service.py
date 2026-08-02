"""Phase 4 — Graph projection service with ACL checks."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models.graph import GraphEntity, GraphEdge
from app.gateway.authorization import get_gateway_authorizer

logger = logging.getLogger(__name__)


class GraphService:
    def upsert_entity(
        self,
        db: Session,
        tenant_id: UUID,
        name: str,
        entity_type: str,
        namespace: str = "weknora",
        kb_id: Optional[UUID] = None,
        source_document_id: Optional[UUID] = None,
        source_revision: Optional[int] = None,
        acl_fingerprint: Optional[str] = None,
        provider_entity_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GraphEntity:
        row = (
            db.query(GraphEntity)
            .filter(
                GraphEntity.tenant_id == tenant_id,
                GraphEntity.namespace == namespace,
                GraphEntity.name == name,
            )
            .first()
        )
        if row:
            row.entity_type = entity_type
            row.kb_id = kb_id
            row.source_document_id = source_document_id
            row.source_revision = source_revision
            row.acl_fingerprint = acl_fingerprint
            row.provider_entity_id = provider_entity_id
            row.metadata_json = metadata or {}
            row.tombstoned_at = None
            db.flush()
            return row

        row = GraphEntity(
            tenant_id=tenant_id,
            kb_id=kb_id,
            namespace=namespace,
            entity_type=entity_type,
            name=name,
            source_document_id=source_document_id,
            source_revision=source_revision,
            acl_fingerprint=acl_fingerprint,
            provider_entity_id=provider_entity_id,
            metadata_json=metadata or {},
        )
        db.add(row)
        db.flush()
        return row

    def upsert_edge(
        self,
        db: Session,
        tenant_id: UUID,
        source_entity_id: UUID,
        target_entity_id: UUID,
        relation_type: str,
        namespace: str = "weknora",
        weight: int = 1,
        source_revision: Optional[int] = None,
        acl_fingerprint: Optional[str] = None,
    ) -> GraphEdge:
        row = (
            db.query(GraphEdge)
            .filter(
                GraphEdge.tenant_id == tenant_id,
                GraphEdge.namespace == namespace,
                GraphEdge.source_entity_id == source_entity_id,
                GraphEdge.target_entity_id == target_entity_id,
                GraphEdge.relation_type == relation_type,
            )
            .first()
        )
        if row:
            row.weight = weight
            row.source_revision = source_revision
            row.acl_fingerprint = acl_fingerprint
            row.tombstoned_at = None
            db.flush()
            return row

        row = GraphEdge(
            tenant_id=tenant_id,
            namespace=namespace,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type,
            weight=weight,
            source_revision=source_revision,
            acl_fingerprint=acl_fingerprint,
        )
        db.add(row)
        db.flush()
        return row

    def tombstone_by_source_document(
        self, db: Session, tenant_id: UUID, document_id: UUID,
    ) -> Dict[str, int]:
        """撤權後 tombstone 源自該文件的 graph entity / 相關 edges。"""
        now = datetime.now(timezone.utc)
        entities = (
            db.query(GraphEntity)
            .filter(
                GraphEntity.tenant_id == tenant_id,
                GraphEntity.source_document_id == document_id,
                GraphEntity.tombstoned_at.is_(None),
            )
            .all()
        )
        entity_ids = [e.id for e in entities]
        for e in entities:
            e.tombstoned_at = now
        edge_count = 0
        if entity_ids:
            edges = (
                db.query(GraphEdge)
                .filter(
                    GraphEdge.tenant_id == tenant_id,
                    GraphEdge.tombstoned_at.is_(None),
                    (
                        GraphEdge.source_entity_id.in_(entity_ids)
                        | GraphEdge.target_entity_id.in_(entity_ids)
                    ),
                )
                .all()
            )
            for edge in edges:
                edge.tombstoned_at = now
                edge_count += 1
        if entities or edge_count:
            db.commit()
        return {"entities": len(entities), "edges": edge_count}

    def _entity_allowed(
        self,
        entity: GraphEntity,
        authz: AuthorizationContext,
        db: Optional[Session] = None,
    ) -> bool:
        if entity.tombstoned_at:
            return False
        # pre-ACL：deny-set 優先於 admin bypass（撤權後不得再遍歷）
        if entity.source_document_id:
            authorizer = get_gateway_authorizer()
            if authorizer.is_denied(str(entity.source_document_id), authz.subject_id):
                return False
        if authz.has_kb_admin:
            return True
        # 部門 + connector source ACL：統一 ResourcePolicyService
        if entity.source_document_id and db is not None:
            try:
                from app.services.resource_policy import get_resource_policy
                from app.models.document import Document
                doc = db.query(Document).filter(Document.id == entity.source_document_id).first()
                if not doc:
                    return False
                return get_resource_policy().authorize_document(db, authz, doc)
            except Exception as exc:
                logger.warning("graph entity ACL lookup failed, deny: %s", exc)
                return False
        if entity.source_document_id and db is None:
            return False
        # 無來源文件綁定的實體：僅 kb_admin 可見（已於上方處理）
        return False

    def traverse(
        self,
        db: Session,
        tenant_id: UUID,
        start_entity_id: UUID,
        authz: AuthorizationContext,
        depth: int = 2,
        namespace: str = "weknora",
    ) -> Dict[str, Any]:
        """BFS traversal with pre/post ACL validation."""
        start = db.query(GraphEntity).filter(
            GraphEntity.id == start_entity_id,
            GraphEntity.tenant_id == tenant_id,
        ).first()
        if not start or not self._entity_allowed(start, authz, db=db):
            return {"entities": [], "edges": [], "denied": True}

        visited: Set[UUID] = set()
        entities: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        frontier = [(start, 0)]

        while frontier:
            entity, level = frontier.pop(0)
            if entity.id in visited or level > depth:
                continue
            if not self._entity_allowed(entity, authz, db=db):
                continue
            visited.add(entity.id)
            entities.append({
                "id": str(entity.id),
                "name": entity.name,
                "entity_type": entity.entity_type,
                "namespace": entity.namespace,
                "depth": level,
            })

            edge_rows = (
                db.query(GraphEdge)
                .filter(
                    GraphEdge.tenant_id == tenant_id,
                    GraphEdge.namespace == namespace,
                    GraphEdge.source_entity_id == entity.id,
                    GraphEdge.tombstoned_at.is_(None),
                )
                .all()
            )
            for edge in edge_rows:
                target = db.query(GraphEntity).filter(GraphEntity.id == edge.target_entity_id).first()
                if target and self._entity_allowed(target, authz, db=db):
                    edges.append({
                        "source": str(edge.source_entity_id),
                        "target": str(edge.target_entity_id),
                        "relation_type": edge.relation_type,
                        "weight": edge.weight,
                    })
                    if target.id not in visited:
                        frontier.append((target, level + 1))

        return {"entities": entities, "edges": edges, "denied": False}

    def search_entities(
        self,
        db: Session,
        tenant_id: UUID,
        query: str,
        authz: AuthorizationContext,
        namespace: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        q = db.query(GraphEntity).filter(
            GraphEntity.tenant_id == tenant_id,
            GraphEntity.tombstoned_at.is_(None),
            GraphEntity.name.ilike(f"%{query}%"),
        )
        if namespace:
            q = q.filter(GraphEntity.namespace == namespace)
        results = []
        for entity in q.limit(limit * 2).all():
            if self._entity_allowed(entity, authz, db=db):
                results.append({
                    "id": str(entity.id),
                    "name": entity.name,
                    "entity_type": entity.entity_type,
                    "namespace": entity.namespace,
                })
            if len(results) >= limit:
                break
        return results
