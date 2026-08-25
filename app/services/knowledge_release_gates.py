"""Deterministic ingestion and KB revision release gates."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.models.document import Document, DocumentChunk
from app.models.kb_maintenance import DocumentVersion
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.models.knowledge_engine import (
    DocumentProfile,
    KnowledgeBaseRevisionDocument,
    LexicalIndexEntry,
    ProcedureGraph,
    ProcedurePhase,
    StructuredRow,
    StructuredTable,
)
from app.services.kb_revision_runtime import canonical_hash


def _load_revision(db, tenant_id: UUID, revision_id: UUID) -> KnowledgeBaseRevision:
    revision = (
        db.query(KnowledgeBaseRevision)
        .join(KnowledgeBase, KnowledgeBaseRevision.kb_id == KnowledgeBase.id)
        .filter(KnowledgeBaseRevision.id == revision_id, KnowledgeBase.tenant_id == tenant_id)
        .first()
    )
    if revision is None:
        raise ValueError("knowledge revision not found for tenant")
    return revision


def _check(name: str, passed: bool, **details: Any) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if passed else "FAIL", **details}


def evaluate_ingest_gate(db, *, tenant_id: UUID, revision_id: UUID) -> dict[str, Any]:
    revision = _load_revision(db, tenant_id, revision_id)
    members = db.query(KnowledgeBaseRevisionDocument).filter(
        KnowledgeBaseRevisionDocument.tenant_id == tenant_id,
        KnowledgeBaseRevisionDocument.kb_revision_id == revision.id,
    ).all()
    member_keys = {(m.document_id, m.document_revision) for m in members}
    profiles = db.query(DocumentProfile).filter(
        DocumentProfile.tenant_id == tenant_id,
    ).all()
    profile_by_key = {(p.document_id, p.document_revision): p for p in profiles}

    missing_profiles = [f"{doc}:{rev}" for doc, rev in sorted(member_keys) if (doc, rev) not in profile_by_key]
    unknown_hashes = [f"{doc}:{rev}" for doc, rev in member_keys
                      if (doc, rev) in profile_by_key and profile_by_key[(doc, rev)].content_hash in {"", "unknown", None}]
    dishonest_scans = [f"{doc}:{rev}" for doc, rev in member_keys if (doc, rev) in profile_by_key
                        and profile_by_key[(doc, rev)].format_family == "pdf_scan"
                        and profile_by_key[(doc, rev)].answer_ready
                        and any(w.get("code") == "scan_without_verified_ocr" for w in (profile_by_key[(doc, rev)].warnings or []))]
    unprofiled_state = [f"{doc}:{rev}" for doc, rev in member_keys if (doc, rev) in profile_by_key
                        and not isinstance(profile_by_key[(doc, rev)].capability_readiness, dict)]

    structured_missing: list[str] = []
    procedure_missing: list[str] = []
    for doc, rev in member_keys:
        profile = profile_by_key.get((doc, rev))
        if profile and (profile.capability_readiness or {}).get("structured_rows"):
            table_ids = [row[0] for row in db.query(StructuredTable.id).filter(
                StructuredTable.tenant_id == tenant_id,
                StructuredTable.document_id == doc,
                StructuredTable.document_revision == rev,
            ).all()]
            row_count = db.query(StructuredRow.id).filter(StructuredRow.table_id.in_(table_ids)).count() if table_ids else 0
            if row_count == 0:
                structured_missing.append(f"{doc}:{rev}")
        if profile and (profile.capability_readiness or {}).get("procedure"):
            graph_ids = [row[0] for row in db.query(ProcedureGraph.id).filter(
                ProcedureGraph.tenant_id == tenant_id,
                ProcedureGraph.document_id == doc,
                ProcedureGraph.document_revision == rev,
            ).all()]
            phase_count = db.query(ProcedurePhase.id).filter(ProcedurePhase.graph_id.in_(graph_ids)).count() if graph_ids else 0
            if phase_count == 0:
                procedure_missing.append(f"{doc}:{rev}")

    checks = [
        _check("candidate_has_members", bool(members), count=len(members)),
        _check("all_members_have_profiles", not missing_profiles, missing=missing_profiles),
        _check("profiles_have_content_manifest", not unknown_hashes, invalid=unknown_hashes),
        _check("scan_is_not_falsely_ready", not dishonest_scans, invalid=dishonest_scans),
        _check("capability_state_is_explicit", not unprofiled_state, invalid=unprofiled_state),
        _check("structured_ready_has_rows", not structured_missing, invalid=structured_missing),
        _check("procedure_ready_has_phases", not procedure_missing, invalid=procedure_missing),
    ]
    return {"revision": revision, "checks": checks, "status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"}


def evaluate_revision_gate(db, *, tenant_id: UUID, revision_id: UUID) -> dict[str, Any]:
    revision = _load_revision(db, tenant_id, revision_id)
    members = db.query(KnowledgeBaseRevisionDocument).filter(
        KnowledgeBaseRevisionDocument.tenant_id == tenant_id,
        KnowledgeBaseRevisionDocument.kb_revision_id == revision.id,
    ).all()
    manifest_docs = (revision.manifest_json or {}).get("documents") or []
    expected_manifest = {(str(m.document_id), str(m.document_version_id), m.document_revision, m.content_hash) for m in members}
    actual_manifest = {(str(x.get("document_id")), str(x.get("document_version_id")), int(x.get("revision") or 0), x.get("content_hash")) for x in manifest_docs}

    snapshot_failures: list[str] = []
    projection_failures: list[str] = []
    unavailable: list[str] = []
    for member in members:
        version = db.query(DocumentVersion).filter(DocumentVersion.id == member.document_version_id).first()
        if version is None or version.document_id != member.document_id or version.version != member.document_revision \
                or canonical_hash(version.content_snapshot or "") != member.content_hash:
            snapshot_failures.append(str(member.document_version_id))
        document = db.query(Document).filter(Document.id == member.document_id).first()
        if document is None or document.tombstoned_at is not None:
            unavailable.append(str(member.document_id))
        chunks = db.query(DocumentChunk.id).filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == member.document_id,
            DocumentChunk.document_revision == member.document_revision,
        ).all()
        chunk_ids = {row[0] for row in chunks}
        indexed = {row[0] for row in db.query(LexicalIndexEntry.chunk_id).filter(
            LexicalIndexEntry.tenant_id == tenant_id,
            LexicalIndexEntry.document_id == member.document_id,
            LexicalIndexEntry.document_revision == member.document_revision,
        ).all()}
        if not chunk_ids or indexed != chunk_ids:
            projection_failures.append(str(member.document_id))

    checks = [
        _check("manifest_matches_membership", bool(members) and expected_manifest == actual_manifest,
               members=len(expected_manifest), manifest=len(actual_manifest)),
        _check("immutable_snapshots_match_hash", not snapshot_failures, invalid=snapshot_failures),
        _check("revision_projection_is_complete", not projection_failures, invalid=projection_failures),
        _check("revoked_or_deleted_sources_absent", not unavailable, invalid=unavailable),
        _check("acl_snapshot_present", all(isinstance(m.acl_snapshot, dict) for m in members)),
    ]
    return {"revision": revision, "checks": checks, "status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"}
