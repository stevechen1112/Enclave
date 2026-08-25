"""Canonical, database-backed truth for whether a document can answer questions."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import and_, func, or_

from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.models.knowledge_engine import DocumentProfile, KnowledgeBaseRevisionDocument


@dataclass(frozen=True)
class DocumentAnswerState:
    answer_ready: bool
    published_revision: int | None
    published_chunk_count: int
    readiness_reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["readiness_reasons"] = list(self.readiness_reasons)
        return payload


def ready_revision_pairs(
    db,
    *,
    tenant_id: UUID,
    kb_revision_ids: Iterable[UUID],
) -> set[tuple[UUID, int]]:
    """Return only immutable members that satisfy the answer-readiness contract."""
    revision_ids = list(kb_revision_ids)
    if not revision_ids:
        return set()
    chunk_exists = (
        db.query(DocumentChunk.id)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == KnowledgeBaseRevisionDocument.document_id,
            DocumentChunk.document_revision
            == KnowledgeBaseRevisionDocument.document_revision,
        )
        .correlate(KnowledgeBaseRevisionDocument)
        .exists()
    )
    rows = (
        db.query(
            KnowledgeBaseRevisionDocument.document_id,
            KnowledgeBaseRevisionDocument.document_revision,
        )
        .join(Document, Document.id == KnowledgeBaseRevisionDocument.document_id)
        .join(
            DocumentProfile,
            and_(
                DocumentProfile.tenant_id == KnowledgeBaseRevisionDocument.tenant_id,
                DocumentProfile.document_id == KnowledgeBaseRevisionDocument.document_id,
                DocumentProfile.document_revision
                == KnowledgeBaseRevisionDocument.document_revision,
            ),
        )
        .filter(
            KnowledgeBaseRevisionDocument.tenant_id == tenant_id,
            KnowledgeBaseRevisionDocument.kb_revision_id.in_(revision_ids),
            DocumentProfile.answer_ready.is_(True),
            Document.tombstoned_at.is_(None),
            or_(
                KnowledgeBaseRevisionDocument.document_revision < Document.version,
                and_(
                    KnowledgeBaseRevisionDocument.document_revision == Document.version,
                    Document.status == "completed",
                ),
            ),
            chunk_exists,
        )
        .distinct()
        .all()
    )
    return {(document_id, int(revision)) for document_id, revision in rows}


def apply_answer_ready_filter(
    query_obj,
    *,
    tenant_id: UUID,
    db,
    kb_revision_ids: Iterable[UUID] | None = None,
):
    """Restrict a Document query to a revision the live retriever may cite."""
    if kb_revision_ids is not None:
        revision_ids = list(kb_revision_ids)
        if not revision_ids:
            return query_obj.filter(False)
    else:
        revision_ids = None
    membership_query = (
        db.query(KnowledgeBaseRevisionDocument.id)
        .join(
            KnowledgeBaseRevision,
            KnowledgeBaseRevision.id == KnowledgeBaseRevisionDocument.kb_revision_id,
        )
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeBaseRevision.kb_id)
        .join(
            DocumentProfile,
            and_(
                DocumentProfile.tenant_id == KnowledgeBaseRevisionDocument.tenant_id,
                DocumentProfile.document_id == KnowledgeBaseRevisionDocument.document_id,
                DocumentProfile.document_revision == KnowledgeBaseRevisionDocument.document_revision,
            ),
        )
        .filter(
            KnowledgeBaseRevisionDocument.tenant_id == tenant_id,
            KnowledgeBaseRevisionDocument.document_id == Document.id,
            KnowledgeBase.tenant_id == tenant_id,
            KnowledgeBase.status == "active",
            KnowledgeBaseRevision.status == "active",
            KnowledgeBaseRevision.revision == KnowledgeBase.active_revision,
            DocumentProfile.answer_ready.is_(True),
            or_(
                KnowledgeBaseRevisionDocument.document_revision < Document.version,
                and_(
                    KnowledgeBaseRevisionDocument.document_revision == Document.version,
                    Document.status == "completed",
                ),
            ),
            db.query(DocumentChunk.id)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == KnowledgeBaseRevisionDocument.document_id,
                DocumentChunk.document_revision
                == KnowledgeBaseRevisionDocument.document_revision,
            )
            .correlate(KnowledgeBaseRevisionDocument)
            .exists(),
        )
    )
    if revision_ids is not None:
        membership_query = membership_query.filter(
            KnowledgeBaseRevisionDocument.kb_revision_id.in_(revision_ids)
        )
    membership_ready = membership_query.correlate(Document).exists()
    return query_obj.filter(membership_ready)


def load_document_answer_states(
    db,
    *,
    tenant_id: UUID,
    documents: Iterable[Document],
    kb_revision_ids: Iterable[UUID] | None = None,
) -> dict[UUID, DocumentAnswerState]:
    """Evaluate active revision membership, profile and chunks in one shared path.

    A newer draft/failed revision does not withdraw an older active revision. A
    tombstone does: revocation is always deny-first across every revision.
    """
    document_map = {document.id: document for document in documents}
    if not document_map:
        return {}

    membership_query = (
        db.query(
            KnowledgeBaseRevisionDocument.document_id,
            KnowledgeBaseRevisionDocument.document_revision,
        )
        .join(
            KnowledgeBaseRevision,
            KnowledgeBaseRevision.id == KnowledgeBaseRevisionDocument.kb_revision_id,
        )
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeBaseRevision.kb_id)
        .filter(
            KnowledgeBaseRevisionDocument.tenant_id == tenant_id,
            KnowledgeBaseRevisionDocument.document_id.in_(document_map),
            KnowledgeBase.tenant_id == tenant_id,
            KnowledgeBase.status == "active",
            KnowledgeBaseRevision.status == "active",
            KnowledgeBaseRevision.revision == KnowledgeBase.active_revision,
        )
    )
    if kb_revision_ids is not None:
        revision_ids = list(kb_revision_ids)
        if not revision_ids:
            memberships = []
        else:
            memberships = membership_query.filter(
                KnowledgeBaseRevisionDocument.kb_revision_id.in_(revision_ids)
            ).all()
    else:
        memberships = membership_query.all()
    member_keys = {(doc_id, revision) for doc_id, revision in memberships}
    revisions_by_document: dict[UUID, list[int]] = {}
    for document_id, revision in member_keys:
        revisions_by_document.setdefault(document_id, []).append(revision)

    profiles = (
        db.query(DocumentProfile.document_id, DocumentProfile.document_revision, DocumentProfile.answer_ready)
        .filter(
            DocumentProfile.tenant_id == tenant_id,
            DocumentProfile.document_id.in_(document_map),
        )
        .all()
    )
    profile_ready = {(doc_id, revision): bool(ready) for doc_id, revision, ready in profiles}
    chunk_rows = (
        db.query(
            DocumentChunk.document_id,
            DocumentChunk.document_revision,
            func.count(DocumentChunk.id),
        )
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id.in_(document_map),
        )
        .group_by(DocumentChunk.document_id, DocumentChunk.document_revision)
        .all()
    )
    chunk_counts = {(doc_id, revision): int(count) for doc_id, revision, count in chunk_rows}

    result: dict[UUID, DocumentAnswerState] = {}
    for document_id, document in document_map.items():
        if document.tombstoned_at is not None:
            result[document_id] = DocumentAnswerState(False, None, 0, ("revoked",))
            continue

        revisions = sorted(revisions_by_document.get(document_id, []), reverse=True)
        if not revisions:
            result[document_id] = DocumentAnswerState(False, None, 0, ("not_in_active_revision",))
            continue

        selected = revisions[0]
        selected_chunks = 0
        reasons: list[str] = []
        for candidate in revisions:
            candidate_reasons: list[str] = []
            candidate_chunks = chunk_counts.get((document_id, candidate), 0)
            if candidate > int(document.version or 1):
                candidate_reasons.append("published_revision_ahead_of_document")
            if candidate == int(document.version or 1) and document.status != "completed":
                candidate_reasons.append("processing_not_completed")
            if (document_id, candidate) not in profile_ready:
                candidate_reasons.append("profile_missing")
            elif not profile_ready[(document_id, candidate)]:
                candidate_reasons.append("profile_not_answer_ready")
            if candidate_chunks <= 0:
                candidate_reasons.append("chunks_missing")
            selected = candidate
            selected_chunks = candidate_chunks
            reasons = candidate_reasons
            if not reasons:
                break

        result[document_id] = DocumentAnswerState(
            answer_ready=not reasons,
            published_revision=selected,
            published_chunk_count=selected_chunks,
            readiness_reasons=tuple(reasons),
        )
    return result


def serialize_document(document: Document, state: DocumentAnswerState) -> dict:
    """Return an ORM-compatible mapping enriched with the canonical state."""
    payload = {column.name: getattr(document, column.name) for column in document.__table__.columns}
    payload.update(state.to_dict())
    return payload
