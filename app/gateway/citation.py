"""
Phase 1 — Citation Builder

Normalize lineage from chunk/wiki/graph results into unified Citation objects.
Optionally enrich from Enclave Document / GatewayResource registry.
"""
from __future__ import annotations

import hashlib
from typing import List, Optional
from uuid import UUID

from app.gateway.contracts import ChunkResult, Citation


class CitationBuilder:
    """Build citation list from retrieval results."""

    def build(
        self,
        results: List[ChunkResult],
        acl_revision: int = 1,
        db=None,
    ) -> List[Citation]:
        citations: List[Citation] = []
        for i, r in enumerate(results):
            doc_id: Optional[UUID] = None
            if r.document_id:
                try:
                    doc_id = UUID(r.document_id)
                except (ValueError, TypeError):
                    doc_id = UUID(int=0)

            meta = dict(r.metadata or {})
            if db is not None and doc_id and doc_id.int != 0:
                meta = self._enrich_from_db(db, doc_id, meta)

            revision = self._coerce_revision(
                meta.get("document_revision"),
                r.document_revision,
                meta.get("version"),
            )
            content_hash = (
                meta.get("content_hash")
                or meta.get("chunk_hash")
                or (hashlib.sha256((r.content or "").encode("utf-8", errors="replace")).hexdigest() if r.content else None)
            )

            citations.append(
                Citation(
                    citation_id=f"cite-{i}",
                    canonical_document_id=doc_id or UUID(int=0),
                    document_revision=revision,
                    artifact_id=r.id or meta.get("artifact_id"),
                    artifact_type=r.result_type or meta.get("artifact_type") or "chunk",
                    source_system=meta.get("source_system"),
                    source_record_id=meta.get("source_record_id"),
                    content_hash=content_hash,
                    page=meta.get("page"),
                    bbox=meta.get("bbox"),
                    section=meta.get("section"),
                    provider=r.provider or meta.get("provider") or "enclave",
                    provider_version=r.provider_version or meta.get("provider_version") or "",
                    acl_revision=acl_revision,
                    retrieval_score=r.score,
                )
            )
        return citations

    def completeness(self, citations: List[Citation], object_level: bool = True) -> dict:
        """
        Lineage completeness metrics for GA gate.

        Base required: canonical_document_id, document_revision, provider, acl_revision.
        Object-level (+): content_hash; and when source_system is a connector, source_record_id.
        """
        if not citations:
            return {"total": 0, "complete": 0, "rate": 1.0, "missing": []}
        required = ["canonical_document_id", "document_revision", "provider", "acl_revision"]
        if object_level:
            required.append("content_hash")
        complete = 0
        missing = []
        for c in citations:
            bad = []
            if not c.canonical_document_id or c.canonical_document_id.int == 0:
                bad.append("canonical_document_id")
            if not c.document_revision:
                bad.append("document_revision")
            if not c.provider:
                bad.append("provider")
            if c.acl_revision is None:
                bad.append("acl_revision")
            if object_level and not c.content_hash:
                bad.append("content_hash")
            if object_level and c.source_system and c.source_system not in (
                "enclave_upload", "file", "upload", None, "",
            ):
                if not c.source_record_id:
                    bad.append("source_record_id")
            if bad:
                missing.append({"citation_id": c.citation_id, "missing": bad})
            else:
                complete += 1
        total = len(citations)
        return {
            "total": total,
            "complete": complete,
            "rate": complete / total,
            "required_fields": required,
            "missing": missing,
        }

    @staticmethod
    def _coerce_revision(*candidates) -> int:
        for value in candidates:
            if value is None or value == "":
                continue
            try:
                return max(1, int(value))
            except (TypeError, ValueError):
                # external_version may be opaque string — hash to stable positive int
                try:
                    return (abs(hash(str(value))) % 1_000_000) + 1
                except Exception:
                    continue
        return 1

    def _enrich_from_db(self, db, doc_id: UUID, meta: dict) -> dict:
        try:
            from app.models.document import Document
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if not doc:
                return meta
            meta.setdefault("source_system", getattr(doc, "source_system", None) or getattr(doc, "source_type", None))
            meta.setdefault("source_record_id", getattr(doc, "source_record_id", None))
            meta.setdefault("content_hash", getattr(doc, "content_hash", None))
            if not meta.get("content_hash"):
                # Prefer any chunk_hash from this document as lineage fingerprint
                try:
                    from app.models.document import DocumentChunk
                    ch = (
                        db.query(DocumentChunk.chunk_hash)
                        .filter(DocumentChunk.document_id == doc_id, DocumentChunk.chunk_hash.isnot(None))
                        .first()
                    )
                    if ch and ch[0]:
                        meta.setdefault("content_hash", ch[0])
                except Exception:
                    pass
            meta.setdefault("version", getattr(doc, "version", None))
            if getattr(doc, "external_version", None):
                meta.setdefault("document_revision", doc.external_version)
            elif getattr(doc, "version", None):
                meta.setdefault("document_revision", doc.version)
            try:
                from app.gateway.resource_registry import ResourceRegistry
                mappings = ResourceRegistry().list_mappings(db, str(doc_id))
                if mappings:
                    meta.setdefault("provider_mappings", mappings)
                    active = next((m for m in mappings if m.get("state") == "active"), mappings[0])
                    meta.setdefault("artifact_id", active.get("provider_resource_id") or meta.get("artifact_id"))
                    if active.get("enclave_revision"):
                        meta.setdefault("document_revision", active["enclave_revision"])
            except Exception:
                pass
            return meta
        except Exception:
            return meta
