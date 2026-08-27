"""Knowledge control center APIs for readiness and immutable releases."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import deps
from app.models.document import Document
from app.models.feedback import ChatFeedback
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.models.knowledge_engine import (
    DocumentProfile,
    EntityRegistry,
    KnowledgeBaseRevisionDocument,
    KnowledgeFreshnessState,
)
from app.models.user import User
from app.services.document_readiness import load_document_answer_states
from app.services.kb_revision_runtime import KBRevisionRuntime
from app.services.release_gate_evidence import (
    REQUIRED_PROMOTION_GATES,
    load_revision_gate_artifacts,
    load_revision_gate_evidence,
)

router = APIRouter(prefix="/knowledge-control")


def _admin(user: User) -> None:
    if not user.is_superuser and user.role not in {"owner", "admin"}:
        raise HTTPException(403, "需要知識庫管理權限")


class CandidateIn(BaseModel):
    kb_id: UUID | None = None
    versions: dict = Field(default_factory=dict)


class TransitionIn(BaseModel):
    target: str


class PromoteIn(BaseModel):
    expected_manifest_hash: str


class EntityIn(BaseModel):
    entity_type: str = Field(min_length=1, max_length=80)
    canonical_key: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=500)
    attributes: dict = Field(default_factory=dict)


class AliasIn(BaseModel):
    alias: str = Field(min_length=1, max_length=500)
    approved: bool = False


class FeedbackProcessIn(BaseModel):
    status: Literal["open", "acknowledged", "resolved"]
    note: str = Field(min_length=1, max_length=2000)
    owner_id: UUID | None = None


def _server_gate_evidence(revision: KnowledgeBaseRevision) -> dict[str, str]:
    """Read server evidence bound to this exact immutable candidate."""
    root = Path(__file__).resolve().parents[4] / "artifacts" / "knowledge"
    return load_revision_gate_evidence(
        root,
        revision_id=str(revision.id),
        manifest_hash=revision.manifest_hash or "",
    )


def _server_gate_artifacts(revision: KnowledgeBaseRevision) -> dict[str, dict]:
    root = Path(__file__).resolve().parents[4] / "artifacts" / "knowledge"
    return load_revision_gate_artifacts(
        root, revision_id=str(revision.id), manifest_hash=revision.manifest_hash or "",
    )


@router.get("/overview")
def overview(db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user)
    profiles = db.query(DocumentProfile).filter(DocumentProfile.tenant_id == current_user.tenant_id).all()
    documents = db.query(Document).filter(
        Document.tenant_id == current_user.tenant_id,
        Document.tombstoned_at.is_(None),
    ).all()
    states = load_document_answer_states(
        db, tenant_id=current_user.tenant_id, documents=documents
    )
    profiles_by_key = {
        (profile.document_id, profile.document_revision): profile for profile in profiles
    }
    readiness = {"ready": 0, "partial": 0, "needs_attention": 0}
    for document in documents:
        state = states[document.id]
        profile = profiles_by_key.get((document.id, state.published_revision))
        if state.answer_ready:
            readiness["ready"] += 1
        elif profile is not None and any((profile.capability_readiness or {}).values()):
            readiness["partial"] += 1
        else:
            readiness["needs_attention"] += 1
    kbs = db.query(KnowledgeBase).filter(KnowledgeBase.tenant_id == current_user.tenant_id).all()
    knowledge_bases = []
    for kb in kbs:
        revisions = []
        for revision in sorted(kb.revisions, key=lambda value: value.revision, reverse=True):
            evidence = _server_gate_evidence(revision)
            revisions.append({
                "id": str(revision.id), "revision": revision.revision, "status": revision.status,
                "manifest_hash": revision.manifest_hash,
                "passed_gates": sorted(evidence),
                "required_gate_count": len(REQUIRED_PROMOTION_GATES),
                "promotion_ready": len(evidence) == len(REQUIRED_PROMOTION_GATES),
            })
        knowledge_bases.append({
            "id": str(kb.id), "name": kb.name, "active_revision": kb.active_revision,
            "revisions": revisions,
        })
    return {"readiness": readiness, "profiled_documents": len(profiles), "knowledge_bases": knowledge_bases}


@router.get("/documents")
def documents(db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user)
    rows = db.query(DocumentProfile).filter(DocumentProfile.tenant_id == current_user.tenant_id).all()
    document_rows = db.query(Document).filter(
        Document.tenant_id == current_user.tenant_id,
        Document.id.in_({profile.document_id for profile in rows}),
    ).all() if rows else []
    states = load_document_answer_states(
        db, tenant_id=current_user.tenant_id, documents=document_rows
    )
    return [{
        "document_id": str(p.document_id),
        "revision": p.document_revision,
        "format": p.format_family,
        "support_level": p.support_level,
        "profile_answer_ready": p.answer_ready,
        "answer_ready": states[p.document_id].answer_ready if p.document_id in states else False,
        "published_revision": states[p.document_id].published_revision if p.document_id in states else None,
        "readiness_reasons": list(states[p.document_id].readiness_reasons) if p.document_id in states else ["document_missing"],
        "capabilities": p.capability_readiness,
        "warnings": p.warnings,
    } for p in rows]


@router.get("/feedback")
def feedback_queue(status: str | None = None, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user)
    query = db.query(ChatFeedback).filter(ChatFeedback.tenant_id == current_user.tenant_id)
    if status:
        query = query.filter(ChatFeedback.status == status)
    rows = query.order_by(ChatFeedback.created_at.desc()).limit(500).all()
    return [{
        "id": str(row.id), "message_id": str(row.message_id), "rating": row.rating,
        "category": row.category, "comment": row.comment, "status": row.status,
        "owner_id": str(row.owner_id), "processing_history": row.processing_history or [],
        "created_at": row.created_at,
    } for row in rows]


@router.patch("/feedback/{feedback_id}")
def process_feedback(feedback_id: UUID, body: FeedbackProcessIn, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user)
    row = db.query(ChatFeedback).filter(
        ChatFeedback.id == feedback_id,
        ChatFeedback.tenant_id == current_user.tenant_id,
    ).first()
    if row is None:
        raise HTTPException(404, "回饋不存在")
    if body.owner_id is not None:
        owner = db.query(User).filter(
            User.id == body.owner_id,
            User.tenant_id == current_user.tenant_id,
            User.status == "active",
        ).first()
        if owner is None:
            raise HTTPException(400, "負責人不存在或不屬於本公司")
        row.owner_id = owner.id
    history = list(row.processing_history or [])
    history.append({
        "status": body.status,
        "note": body.note.strip(),
        "actor_id": str(current_user.id),
        "at": datetime.now(timezone.utc).isoformat(),
    })
    row.status = body.status
    row.processing_history = history
    db.commit(); db.refresh(row)
    return {"id": str(row.id), "status": row.status, "owner_id": str(row.owner_id), "processing_history": row.processing_history}


@router.get("/freshness")
def freshness(status: str | None = None, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user)
    query = db.query(KnowledgeFreshnessState).filter(KnowledgeFreshnessState.tenant_id == current_user.tenant_id)
    if status:
        query = query.filter(KnowledgeFreshnessState.state == status)
    rows = query.order_by(KnowledgeFreshnessState.state, KnowledgeFreshnessState.document_id).all()
    return [{
        "id": str(row.id), "document_id": str(row.document_id), "state": row.state,
        "reasons": row.reasons or [], "owner_id": str(row.owner_id) if row.owner_id else None,
        "review_due_at": row.review_due_at, "last_reviewed_at": row.last_reviewed_at,
        "upstream_sync_at": row.upstream_sync_at,
    } for row in rows]


@router.post("/freshness/scan")
def scan_freshness(current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user)
    from app.tasks.kb_maintenance_tasks import refresh_knowledge_freshness_task
    task = refresh_knowledge_freshness_task.delay(str(current_user.tenant_id))
    return {"task_id": task.id, "status": "queued"}


@router.post("/revisions/candidate")
def create_candidate(body: CandidateIn, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user); runtime = KBRevisionRuntime()
    if body.kb_id:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == body.kb_id, KnowledgeBase.tenant_id == current_user.tenant_id).first()
        if not kb: raise HTTPException(404, "知識庫不存在")
    else:
        kb = runtime.ensure_default_kb(db, tenant_id=current_user.tenant_id)
    versions = runtime.snapshot_current_documents(db, tenant_id=current_user.tenant_id, kb=kb)
    if not versions: raise HTTPException(400, "沒有可建立版本的 completed 文件")
    rev = runtime.create_candidate(db, kb=kb, document_versions=versions, manifest_versions=body.versions)
    db.commit(); db.refresh(rev)
    return {"id": str(rev.id), "kb_id": str(kb.id), "revision": rev.revision, "status": rev.status,
            "manifest_hash": rev.manifest_hash, "members": len(rev.revision_documents)}


def _revision(db, user, revision_id):
    return db.query(KnowledgeBaseRevision).join(KnowledgeBase).filter(KnowledgeBaseRevision.id == revision_id,
        KnowledgeBase.tenant_id == user.tenant_id).first()


@router.post("/revisions/{revision_id}/transition")
def transition(revision_id: UUID, body: TransitionIn, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user); rev = _revision(db, current_user, revision_id)
    if not rev: raise HTTPException(404, "知識版本不存在")
    try: KBRevisionRuntime().transition(rev, body.target)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    db.commit(); return {"id": str(rev.id), "status": rev.status}


@router.post("/revisions/{revision_id}/promote")
def promote(revision_id: UUID, body: PromoteIn, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user); rev = _revision(db, current_user, revision_id)
    if not rev: raise HTTPException(404, "知識版本不存在")
    if body.expected_manifest_hash != rev.manifest_hash:
        raise HTTPException(409, "候選版本內容已變更，請重新整理後再發布")
    artifacts = _server_gate_artifacts(rev)
    runtime_manifest = (artifacts.get("KB-SHADOW-01") or {}).get("runtime_manifest")
    runtime_image = str((runtime_manifest or {}).get("image_digest") or "")
    mismatched_images = sorted(
        gate for gate, artifact in artifacts.items()
        if str(artifact.get("image_digest") or "") != runtime_image
    )
    if mismatched_images:
        raise HTTPException(409, "發布證據不是由同一個最終映像產生：" + "、".join(mismatched_images))
    try: KBRevisionRuntime().promote(
        db, kb=rev.kb, revision=rev,
        gate_evidence={gate: "PASS" for gate in artifacts},
        runtime_manifest=runtime_manifest,
        gate_artifacts=artifacts,
        created_by=current_user.id,
    )
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    db.commit(); return {"id": str(rev.id), "status": rev.status, "active_revision": rev.kb.active_revision}


@router.post("/revisions/{revision_id}/rollback")
def rollback(revision_id: UUID, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user); rev = _revision(db, current_user, revision_id)
    if not rev: raise HTTPException(404, "知識版本不存在")
    try: KBRevisionRuntime().rollback(db, kb=rev.kb, target=rev, executed_by=current_user.id)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    db.commit(); return {"id": str(rev.id), "status": rev.status, "active_revision": rev.kb.active_revision}


@router.get("/revisions/{revision_id}/members")
def members(revision_id: UUID, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user)
    rev = _revision(db, current_user, revision_id)
    if not rev: raise HTTPException(404, "知識版本不存在")
    rows = db.query(KnowledgeBaseRevisionDocument).filter(KnowledgeBaseRevisionDocument.kb_revision_id == rev.id).all()
    return [{"document_id": str(m.document_id), "document_version_id": str(m.document_version_id),
             "document_revision": m.document_revision, "content_hash": m.content_hash,
             "policy_revision": m.policy_revision} for m in rows]


@router.get("/entities")
def entities(db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user)
    rows = db.query(EntityRegistry).filter(EntityRegistry.tenant_id == current_user.tenant_id).order_by(EntityRegistry.entity_type, EntityRegistry.display_name).all()
    return [{"id": str(row.id), "entity_type": row.entity_type, "canonical_key": row.canonical_key,
             "display_name": row.display_name, "attributes": row.attributes_json, "status": row.status,
             "aliases": [{"id": str(alias.id), "alias": alias.alias, "approved": alias.approved} for alias in row.aliases]} for row in rows]


@router.post("/entities")
def create_entity(body: EntityIn, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user)
    row = EntityRegistry(tenant_id=current_user.tenant_id, entity_type=body.entity_type.strip(),
                         canonical_key=body.canonical_key.strip(), display_name=body.display_name.strip(),
                         attributes_json=body.attributes, status="active")
    db.add(row)
    try: db.commit(); db.refresh(row)
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "同類型已有相同的正式代號") from exc
    return {"id": str(row.id), "entity_type": row.entity_type, "canonical_key": row.canonical_key, "display_name": row.display_name}


@router.post("/entities/{entity_id}/aliases")
def create_entity_alias(entity_id: UUID, body: AliasIn, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_user)):
    _admin(current_user)
    entity = db.query(EntityRegistry).filter(EntityRegistry.id == entity_id, EntityRegistry.tenant_id == current_user.tenant_id).first()
    if not entity: raise HTTPException(404, "正式名稱不存在")
    from app.services.entity_registry import add_alias
    try:
        alias = add_alias(db, entity=entity, alias=body.alias, approved=body.approved)
        db.commit(); db.refresh(alias)
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "這個別名已登記") from exc
    return {"id": str(alias.id), "alias": alias.alias, "approved": alias.approved}
