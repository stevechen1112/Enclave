import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _add_ready_profile(db, document, revision: int) -> None:
    from app.models.knowledge_engine import DocumentProfile

    db.add(
        DocumentProfile(
            tenant_id=document.tenant_id,
            document_id=document.id,
            document_revision=revision,
            format_family="text",
            support_level="full",
            language_profile={},
            structure_map={},
            capability_readiness={"narrative": True},
            warnings=[],
            answer_ready=True,
            profiler_version="test",
            content_hash="a" * 64,
        )
    )


@pytest.mark.asyncio
async def test_candidate_membership_is_immutable_and_browser_cannot_self_approve(client, superuser_headers, test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.models.document import Document, DocumentChunk

    me = await client.get("/api/v1/users/me", headers=superuser_headers)
    assert me.status_code == 200
    tenant_id = uuid.UUID(me.json()["tenant_id"])
    db = sessionmaker(bind=test_engine)()
    try:
        doc = Document(tenant_id=tenant_id, filename=f"release-{uuid.uuid4().hex}.txt", file_type="txt",
                       status="completed", content_hash=uuid.uuid4().hex, version=1)
        db.add(doc); db.flush()
        db.add(DocumentChunk(tenant_id=tenant_id, document_id=doc.id, chunk_index=0,
                             text="正式版本內容", chunk_hash=uuid.uuid4().hex))
        db.commit()
    finally:
        db.close()

    made = await client.post("/api/v1/knowledge-control/revisions/candidate", json={"versions": {}}, headers=superuser_headers)
    assert made.status_code == 200, made.text
    body = made.json(); assert body["members"] >= 1 and body["status"] == "candidate"
    moved = await client.post(f"/api/v1/knowledge-control/revisions/{body['id']}/transition", json={"target": "shadow"}, headers=superuser_headers)
    assert moved.status_code == 200
    promoted = await client.post(f"/api/v1/knowledge-control/revisions/{body['id']}/promote",
                                 json={"expected_manifest_hash": body["manifest_hash"]}, headers=superuser_headers)
    assert promoted.status_code == 409
    assert "gates" in promoted.text.lower() or "閘門" in promoted.text


@pytest.mark.asyncio
async def test_employee_cannot_open_knowledge_control(client, superuser_headers):
    from tests.conftest import create_tenant, create_user, login_user
    tenant = await create_tenant(client, superuser_headers, {"name": f"KBC-{uuid.uuid4().hex}", "plan": "free"})
    email = f"employee-{uuid.uuid4().hex}@example.com"
    await create_user(client, superuser_headers, {"email": email, "password": "Pass12345!", "full_name": "Employee", "role": "employee", "tenant_id": tenant["id"]})
    headers = await login_user(client, email, "Pass12345!")
    response = await client.get("/api/v1/knowledge-control/overview", headers=headers)
    assert response.status_code == 403
    response = await client.get(f"/api/v1/knowledge-control/revisions/{uuid.uuid4()}/members", headers=headers)
    assert response.status_code == 403


def test_release_evidence_is_bound_to_exact_revision_and_manifest(tmp_path):
    import json
    from app.services.release_gate_evidence import load_revision_gate_evidence

    for gate, filename in {
        "KB-INGEST-01": "ingest_gate_last_run.json",
        "KB-REV-01": "revision_gate_last_run.json",
    }.items():
        (tmp_path / filename).write_text(json.dumps({
            "schema_version": 1,
            "gate": gate,
            "status": "PASS",
            "revision_id": "old-revision",
            "manifest_hash": "old-manifest",
        }), encoding="utf-8")
    assert load_revision_gate_evidence(tmp_path, revision_id="new", manifest_hash="new") == {}

    for gate, filename in {
        "KB-INGEST-01": "ingest_gate_last_run.json",
        "KB-REV-01": "revision_gate_last_run.json",
    }.items():
        (tmp_path / filename).write_text(json.dumps({
            "schema_version": 1,
            "gate": gate,
            "status": "PASS",
            "revision_id": "new",
            "manifest_hash": "new",
        }), encoding="utf-8")
    assert load_revision_gate_evidence(tmp_path, revision_id="new", manifest_hash="new") == {
        "KB-INGEST-01": "PASS",
        "KB-REV-01": "PASS",
    }


@pytest.mark.asyncio
async def test_promote_and_rollback_leave_release_audit_chain(client, superuser_headers, test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.models.knowledge_base import KnowledgeBaseRevision
    from app.models.knowledge_engine import KnowledgeRelease, RollbackPoint, RuntimeRelease
    from app.services.kb_revision_runtime import KBRevisionRuntime
    from app.services.release_gate_evidence import REQUIRED_PROMOTION_GATES

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"])
    db = sessionmaker(bind=test_engine)()
    try:
        runtime = KBRevisionRuntime()
        kb = runtime.ensure_default_kb(db, tenant_id=tenant_id)
        base = max([revision.revision for revision in kb.revisions] or [0])
        first = KnowledgeBaseRevision(
            kb_id=kb.id, revision=base + 1, status="shadow",
            manifest_hash=uuid.uuid4().hex, manifest_json={}, policy_revision=1,
        )
        second = KnowledgeBaseRevision(
            kb_id=kb.id, revision=base + 2, status="shadow",
            manifest_hash=uuid.uuid4().hex, manifest_json={}, policy_revision=1,
        )
        db.add_all([first, second]); db.flush()
        evidence = {gate: "PASS" for gate in REQUIRED_PROMOTION_GATES}
        runtime_manifest = {
            "image_digest": "sha256:" + "a" * 64,
            "frontend_image_digest": "sha256:" + "c" * 64,
            "deployment_manifest_id": "dm-" + "d" * 24,
            "model_manifest": {"answer": "test-model"},
            "prompt_hash": "b" * 64,
            "feature_flags": {"knowledge_engine": True},
        }
        artifacts = {gate: {"image_digest": runtime_manifest["image_digest"]} for gate in REQUIRED_PROMOTION_GATES}
        artifacts["KB-UX-01"].update({
            "frontend_image_digest": runtime_manifest["frontend_image_digest"],
            "deployment_manifest_id": runtime_manifest["deployment_manifest_id"],
        })

        runtime.promote(db, kb=kb, revision=first, gate_evidence=evidence, runtime_manifest=runtime_manifest, gate_artifacts=artifacts)
        runtime.promote(db, kb=kb, revision=second, gate_evidence=evidence, runtime_manifest=runtime_manifest, gate_artifacts=artifacts)
        runtime.rollback(db, kb=kb, target=first, executed_by=uuid.UUID(me["id"]))

        releases = db.query(KnowledgeRelease).filter(KnowledgeRelease.kb_id == kb.id).all()
        assert len(releases) == 2
        assert {release.status for release in releases} == {"active", "rolled_back"}
        point = db.query(RollbackPoint).filter(RollbackPoint.kb_id == kb.id).one()
        assert point.from_release_id != point.to_release_id
        assert point.executed_by == uuid.UUID(me["id"])
        assert all(release.runtime_release_id for release in releases)
        runtime_releases = db.query(RuntimeRelease).filter(RuntimeRelease.id.in_([
            release.runtime_release_id for release in releases
        ])).all()
        assert {row.frontend_image_digest for row in runtime_releases} == {runtime_manifest["frontend_image_digest"]}
        assert {row.deployment_manifest_id for row in runtime_releases} == {runtime_manifest["deployment_manifest_id"]}
        assert first.status == "active" and second.status == "retired"
        assert kb.active_revision == first.revision
    finally:
        db.rollback(); db.close()


def test_promotion_rejects_gate_artifact_from_another_image(test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
    from app.models.tenant import Tenant
    from app.services.kb_revision_runtime import KBRevisionRuntime
    from app.services.release_gate_evidence import REQUIRED_PROMOTION_GATES

    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name=f"Image-{uuid.uuid4().hex}", status="active")
        kb = KnowledgeBase(tenant_id=tenant.id, name="Image-bound", status="active")
        revision = KnowledgeBaseRevision(kb=kb, revision=1, status="shadow", manifest_json={})
        db.add_all([tenant, kb, revision]); db.flush()
        image = "sha256:" + "a" * 64
        frontend = "sha256:" + "b" * 64
        deployment_manifest_id = "dm-" + "d" * 24
        evidence = {gate: "PASS" for gate in REQUIRED_PROMOTION_GATES}
        artifacts = {gate: {"image_digest": image} for gate in REQUIRED_PROMOTION_GATES}
        artifacts["KB-UX-01"] = {
            "image_digest": "sha256:" + "c" * 64,
            "frontend_image_digest": frontend,
            "deployment_manifest_id": deployment_manifest_id,
        }
        with pytest.raises(ValueError, match="release image"):
            KBRevisionRuntime().promote(
                db, kb=kb, revision=revision, gate_evidence=evidence,
                runtime_manifest={"image_digest": image, "frontend_image_digest": frontend,
                                  "deployment_manifest_id": deployment_manifest_id,
                                  "model_manifest": {"answer": "m"}, "prompt_hash": "b" * 64,
                                  "feature_flags": {}},
                gate_artifacts=artifacts,
            )
    finally:
        db.rollback(); db.close()


def test_promotion_rejects_browser_evidence_from_another_frontend(test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
    from app.models.tenant import Tenant
    from app.services.kb_revision_runtime import KBRevisionRuntime
    from app.services.release_gate_evidence import REQUIRED_PROMOTION_GATES

    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name=f"Frontend-{uuid.uuid4().hex}", status="active")
        kb = KnowledgeBase(tenant_id=tenant.id, name="Frontend-bound", status="active")
        revision = KnowledgeBaseRevision(kb=kb, revision=1, status="shadow", manifest_json={})
        db.add_all([tenant, kb, revision]); db.flush()
        backend = "sha256:" + "a" * 64
        frontend = "sha256:" + "b" * 64
        manifest_id = "dm-" + "c" * 24
        evidence = {gate: "PASS" for gate in REQUIRED_PROMOTION_GATES}
        artifacts = {gate: {"image_digest": backend} for gate in REQUIRED_PROMOTION_GATES}
        artifacts["KB-UX-01"].update({
            "frontend_image_digest": "sha256:" + "d" * 64,
            "deployment_manifest_id": manifest_id,
        })
        with pytest.raises(ValueError, match="browser acceptance"):
            KBRevisionRuntime().promote(
                db, kb=kb, revision=revision, gate_evidence=evidence,
                runtime_manifest={"image_digest": backend, "frontend_image_digest": frontend,
                                  "deployment_manifest_id": manifest_id,
                                  "model_manifest": {"answer": "m"}, "prompt_hash": "e" * 64,
                                  "feature_flags": {}},
                gate_artifacts=artifacts,
            )
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_chunk_reads_are_isolated_by_document_revision(client, superuser_headers, test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.models.document import Document, DocumentChunk
    from app.models.kb_maintenance import DocumentVersion
    from app.services.kb_revision_runtime import KBRevisionRuntime
    from app.services.kb_retrieval import KnowledgeBaseRetriever

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"])
    db = sessionmaker(bind=test_engine)()
    try:
        doc = Document(tenant_id=tenant_id, filename="revision-isolation.txt", file_type="txt", status="completed", version=2)
        db.add(doc); db.flush()
        old = DocumentChunk(tenant_id=tenant_id, document_id=doc.id, document_revision=1, chunk_index=0,
                            text="舊版內容", chunk_hash=uuid.uuid4().hex)
        current = DocumentChunk(tenant_id=tenant_id, document_id=doc.id, document_revision=2, chunk_index=0,
                                text="新版內容", chunk_hash=uuid.uuid4().hex)
        v1 = DocumentVersion(tenant_id=tenant_id, document_id=doc.id, version=1, filename=doc.filename,
                             status="completed", content_snapshot="舊版內容")
        v2 = DocumentVersion(tenant_id=tenant_id, document_id=doc.id, version=2, filename=doc.filename,
                             status="completed", content_snapshot="新版內容")
        db.add_all([old, current, v1, v2]); db.flush()
        runtime = KBRevisionRuntime(); kb = runtime.ensure_default_kb(db, tenant_id=tenant_id)
        r1 = runtime.create_candidate(db, kb=kb, document_versions=[v1])
        _add_ready_profile(db, doc, 1)
        db.flush()

        base = db.query(DocumentChunk).join(Document, DocumentChunk.document_id == Document.id).filter(Document.id == doc.id)
        doc.status = "pending_review"; db.flush()
        historical_q = KnowledgeBaseRetriever._apply_document_lifecycle_scope(base, {"kb_revision_id": str(r1.id)})
        historical = KnowledgeBaseRetriever._apply_kb_revision_scope(historical_q, {"kb_revision_id": str(r1.id)}, db).all()
        live_q = KnowledgeBaseRetriever._apply_document_lifecycle_scope(base, None)
        live = KnowledgeBaseRetriever._apply_kb_revision_scope(live_q, None, db).all()
        assert [row.text for row in historical] == ["舊版內容"]
        assert live == []
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_knowhow_hot_path_excludes_unreviewed_expired_and_future_cards(client, superuser_headers, test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.models.mka import KnowhowCardModel
    from app.services.mka_persistence import MKARepository

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"]); reviewer_id = uuid.UUID(me["id"])
    now = datetime.now(timezone.utc)
    db = sessionmaker(bind=test_engine)()
    try:
        common = {"tenant_id": tenant_id, "title": "師傅知識", "status": "approved",
                  "reviewer": reviewer_id, "reviewed_at": now}
        rows = [
            KnowhowCardModel(card_id=f"valid-{uuid.uuid4().hex}", **common),
            KnowhowCardModel(card_id=f"expired-{uuid.uuid4().hex}", expires_at=now-timedelta(days=1), **common),
            KnowhowCardModel(card_id=f"future-{uuid.uuid4().hex}", effective_from=now+timedelta(days=1), **common),
            KnowhowCardModel(card_id=f"overdue-{uuid.uuid4().hex}", review_due_at=now-timedelta(days=1), **common),
            KnowhowCardModel(card_id=f"unreviewed-{uuid.uuid4().hex}", tenant_id=tenant_id, title="未複核",
                             status="approved", reviewer=None, reviewed_at=None),
        ]
        db.add_all(rows); db.flush()
        found = MKARepository(db).list_approved_knowhow(tenant_id=tenant_id)
        ids = {row.card_id for row in found}
        assert rows[0].card_id in ids
        assert all(row.card_id not in ids for row in rows[1:])
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_evaluation_preserves_first_run_and_reports_real_denominators(client, superuser_headers, test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.services.knowledge_evaluation import add_results, finalize_run, start_run

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"])
    db = sessionmaker(bind=test_engine)()
    try:
        kwargs = {"tenant_id": tenant_id, "split": f"sealed-{uuid.uuid4().hex}",
                  "corpus_hash": "a" * 64, "question_hash": "b" * 64,
                  "scoring_hash": "c" * 64, "runtime_manifest": {"image": "sha256:test"}}
        first = start_run(db, **kwargs)
        add_results(db, first, [
            {"case_id": "1", "domain": "manufacturing", "case_type": "number", "verdict": "PASS"},
            {"case_id": "2", "domain": "manufacturing", "case_type": "number", "verdict": "FAIL", "critical_error": True},
            {"case_id": "3", "domain": "legal", "case_type": "scope", "verdict": "BLOCKED"},
            {"case_id": "4", "domain": "legal", "case_type": "scope", "verdict": "REVIEW"},
        ])
        summary = finalize_run(db, first)
        assert first.first_run is True
        assert summary["total"] == 4
        assert summary["strict_assertions"]["numerator"] == 1
        assert summary["strict_assertions"]["denominator"] == 2
        assert summary["critical_errors"] == 1
        with pytest.raises(ValueError):
            add_results(db, first, [{"case_id": "late", "verdict": "PASS"}])

        repeat = start_run(db, **kwargs)
        assert repeat.first_run is False
        assert repeat.baseline_run_id == first.id
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_csv_projection_preserves_row_identity_and_field_lineage(client, superuser_headers, test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.models.document import Document
    from app.models.knowledge_engine import StructuredField, StructuredRow, StructuredTable
    from app.services.structured_projection import upsert_structured_projection

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"]); db = sessionmaker(bind=test_engine)()
    try:
        doc = Document(tenant_id=tenant_id, filename="quotes.csv", file_type="csv", status="completed", version=3)
        db.add(doc); db.flush()
        count = upsert_structured_projection(db, doc, "客戶編號 | 單價 | 交期\n--- | --- | ---\nC-01 | 120 | 2026-09-01\nC-02 | 180 | 2026-10-01")
        assert count == 2
        table = db.query(StructuredTable).filter(StructuredTable.document_id == doc.id).one()
        rows = db.query(StructuredRow).filter(StructuredRow.table_id == table.id).order_by(StructuredRow.row_number).all()
        assert rows[0].identity_json == {"客戶編號": "C-01"}
        fields = db.query(StructuredField).filter(StructuredField.row_id == rows[0].id).all()
        assert {field.field_name: field.raw_value for field in fields} == {"客戶編號": "C-01", "單價": "120", "交期": "2026-09-01"}
        typed = {field.field_name: (field.value_type, field.normalized_value) for field in fields}
        assert typed["單價"] == ("money", {"value": 120, "raw": "120"})
        assert typed["交期"] == ("date", {"value": "2026-09-01"})
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_procedure_projection_preserves_order_condition_and_completion(client, superuser_headers, test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.models.document import Document
    from app.models.knowledge_engine import ProcedureGraph, ProcedurePhase
    from app.services.procedure_projection import project_procedure

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"]); db = sessionmaker(bind=test_engine)()
    try:
        doc = Document(tenant_id=tenant_id, filename="停機SOP.md", file_type="md", status="completed", version=1)
        db.add(doc); db.flush()
        assert project_procedure(db, doc, "# 安全停機\n1. 按下停止鍵\n2. 如果溫度過高，則等待降溫\n3. 確認電源關閉") == 3
        graph = db.query(ProcedureGraph).filter(ProcedureGraph.document_id == doc.id).one()
        phases = db.query(ProcedurePhase).filter(ProcedurePhase.graph_id == graph.id).order_by(ProcedurePhase.sequence).all()
        assert [phase.phase_key for phase in phases] == ["step-1", "step-2", "step-3"]
        assert phases[1].condition_json == {"raw": "溫度過高"}
        assert phases[-1].completion_criteria == "流程完成"
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_structured_retrieval_never_combines_fields_across_rows(client, superuser_headers, test_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.core.authorization import AuthorizationContext
    from app.models.document import Document
    from app.services.projection_retrieval import load_structured_evidence
    from app.services.query_plan import build_query_plan
    from app.services.structured_projection import upsert_structured_projection

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"]); db = sessionmaker(bind=test_engine)()
    try:
        doc = Document(tenant_id=tenant_id, filename="報價資料.csv", file_type="csv", status="completed", version=1)
        db.add(doc); db.flush()
        upsert_structured_projection(
            db, doc,
            "客戶編號 | 單價 | 交期\n--- | --- | ---\nC-01 | 120 | 2026-09-01\nC-02 | 180 | 2026-10-01",
        )
        monkeypatch.setattr("app.services.projection_retrieval.deny_set_allows", lambda *_a, **_k: True)
        authz = AuthorizationContext(tenant_id=tenant_id, subject_id=uuid.uuid4(), role_ids=["kb_admin"])

        exact = load_structured_evidence(
            db=db, authz=authz, question="C-01 的單價與交期日期？",
            plan=build_query_plan("C-01 的單價與交期日期？"), scope={},
        )
        assert len(exact) == 1
        assert "單價：120" in exact[0]["content"] and "交期：2026-09-01" in exact[0]["content"]
        assert "180" not in exact[0]["content"]
        assert exact[0]["metadata"]["row_id"]

        ambiguous = load_structured_evidence(
            db=db, authz=authz, question="單價與交期日期？",
            plan=build_query_plan("單價與交期日期？"), scope={},
        )
        assert len(ambiguous) == 1
        assert ambiguous[0]["metadata"]["evidence_kind"] == "structured_ambiguity"
        assert "120" not in ambiguous[0]["content"] and "180" not in ambiguous[0]["content"]
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_structured_retrieval_uses_one_of_multiple_row_identity_fields(client, superuser_headers, test_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.core.authorization import AuthorizationContext
    from app.models.document import Document
    from app.services.projection_retrieval import load_structured_evidence
    from app.services.query_plan import build_query_plan
    from app.services.structured_projection import upsert_structured_projection

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"]); db = sessionmaker(bind=test_engine)()
    try:
        doc = Document(tenant_id=tenant_id, filename="客戶報價.csv", file_type="csv", status="completed", version=1)
        db.add(doc); db.flush()
        upsert_structured_projection(
            db, doc,
            "客戶編號 | 客戶名稱 | 單價\n--- | --- | ---\nC-01 | 甲公司 | 120\nC-02 | 乙公司 | 180",
        )
        monkeypatch.setattr("app.services.projection_retrieval.deny_set_allows", lambda *_a, **_k: True)
        authz = AuthorizationContext(tenant_id=tenant_id, subject_id=uuid.uuid4(), role_ids=["kb_admin"])
        result = load_structured_evidence(
            db=db, authz=authz, question="C-01 的單價？", plan=build_query_plan("C-01 的單價？"), scope={},
        )
        assert len(result) == 1 and "單價：120" in result[0]["content"] and "180" not in result[0]["content"]
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_procedure_retrieval_exposes_unresolved_branch_instead_of_guessing(client, superuser_headers, test_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.core.authorization import AuthorizationContext
    from app.models.document import Document
    from app.services.procedure_projection import project_procedure
    from app.services.projection_retrieval import load_procedure_evidence
    from app.services.query_plan import build_query_plan

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"]); db = sessionmaker(bind=test_engine)()
    try:
        doc = Document(tenant_id=tenant_id, filename="安全停機SOP.md", file_type="md", status="completed", version=1)
        db.add(doc); db.flush()
        project_procedure(db, doc, "# 安全停機\n1. 按下停止鍵\n2. 如果溫度過高，則等待降溫\n3. 確認電源關閉")
        monkeypatch.setattr("app.services.projection_retrieval.deny_set_allows", lambda *_a, **_k: True)
        authz = AuthorizationContext(tenant_id=tenant_id, subject_id=uuid.uuid4(), role_ids=["kb_admin"])

        unresolved = load_procedure_evidence(
            db=db, authz=authz, question="安全停機流程有哪些步驟？",
            plan=build_query_plan("安全停機流程有哪些步驟？"), scope={},
        )
        assert unresolved and unresolved[0]["metadata"]["procedure_status"] == "partial"
        assert "未確認前不得自行選擇分支" in unresolved[0]["content"]
        assert "等待降溫" not in unresolved[0]["content"]

        resolved = load_procedure_evidence(
            db=db, authz=authz, question="溫度過高時，安全停機流程有哪些步驟？",
            plan=build_query_plan("溫度過高時，安全停機流程有哪些步驟？"), scope={},
        )
        assert resolved[0]["metadata"]["procedure_status"] == "complete"
        assert "等待降溫" in resolved[0]["content"]
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_entity_registry_only_uses_tenant_approved_aliases(client, superuser_headers, test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.models.knowledge_engine import EntityRegistry
    from app.services.entity_registry import add_alias, resolve_entity

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"]); db = sessionmaker(bind=test_engine)()
    try:
        entity = EntityRegistry(tenant_id=tenant_id, entity_type="equipment", canonical_key="P-200",
                                display_name="P-200 精密設備", attributes_json={}, status="active")
        db.add(entity); db.flush()
        add_alias(db, entity=entity, alias="P 200", approved=True)
        add_alias(db, entity=entity, alias="二號機", approved=False)
        assert resolve_entity(db, tenant_id=tenant_id, value="Ｐ－２００", entity_type="equipment").status == "resolved"
        assert resolve_entity(db, tenant_id=tenant_id, value="二號機", entity_type="equipment").status == "not_found"
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_feedback_queue_has_owner_status_and_append_only_processing_history(client, superuser_headers, test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.models.chat import Conversation, Message
    from app.models.feedback import ChatFeedback

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"]); user_id = uuid.UUID(me["id"])
    db = sessionmaker(bind=test_engine)()
    try:
        conversation = Conversation(tenant_id=tenant_id, user_id=user_id, title="品質回饋")
        db.add(conversation); db.flush()
        message = Message(conversation_id=conversation.id, role="assistant", content="測試回答")
        db.add(message); db.flush()
        row = ChatFeedback(
            tenant_id=tenant_id, message_id=message.id, user_id=user_id,
            rating=1, category="wrong_number", comment="金額錯誤",
            owner_id=user_id, status="open",
            processing_history=[{"status": "open", "actor_id": str(user_id)}],
        )
        db.add(row); db.commit(); feedback_id = row.id
    finally:
        db.close()

    listed = await client.get("/api/v1/knowledge-control/feedback?status=open", headers=superuser_headers)
    assert listed.status_code == 200
    found = next(item for item in listed.json() if item["id"] == str(feedback_id))
    assert found["owner_id"] == str(user_id) and found["status"] == "open"
    assert len(found["processing_history"]) == 1

    processed = await client.patch(
        f"/api/v1/knowledge-control/feedback/{feedback_id}",
        json={"status": "resolved", "note": "已核對來源並建立候選修正"},
        headers=superuser_headers,
    )
    assert processed.status_code == 200, processed.text
    assert processed.json()["status"] == "resolved"
    assert len(processed.json()["processing_history"]) == 2


@pytest.mark.asyncio
async def test_freshness_scan_marks_overdue_without_changing_document(client, superuser_headers, test_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.models.document import Document
    from app.models.knowledge_engine import KnowledgeFreshnessState
    from app.tasks import kb_maintenance_tasks

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"])
    Session = sessionmaker(bind=test_engine)
    setup = Session()
    try:
        document = Document(
            tenant_id=tenant_id, filename=f"freshness-{uuid.uuid4().hex}.txt",
            file_type="txt", status="completed", version=1,
        )
        setup.add(document); setup.flush()
        state = KnowledgeFreshnessState(
            tenant_id=tenant_id, document_id=document.id,
            review_due_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        setup.add(state); setup.commit(); document_id = document.id
    finally:
        setup.close()

    monkeypatch.setattr(kb_maintenance_tasks, "SessionLocal", Session)
    assert kb_maintenance_tasks.refresh_knowledge_freshness_task.run(str(tenant_id)) >= 1
    verify = Session()
    try:
        state = verify.query(KnowledgeFreshnessState).filter_by(document_id=document_id).one()
        document = verify.query(Document).filter_by(id=document_id).one()
        assert state.state == "review_overdue"
        assert state.reasons == ["review_due_at_passed"]
        assert document.status == "completed"
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_kb_scope_is_fail_closed_for_non_member_and_candidate_reader(client, superuser_headers, test_engine):
    from sqlalchemy.orm import sessionmaker
    from app.core.authorization import AuthorizationContext
    from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseMember, KnowledgeBaseRevision
    from app.models.tenant import Tenant
    from app.services.kb_scope_policy import resolve_kb_revision_scope

    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name=f"Scope-{uuid.uuid4().hex}", status="active")
        db.add(tenant); db.flush()
        kb = KnowledgeBase(tenant_id=tenant.id, name="Restricted", status="active", active_revision=1)
        db.add(kb); db.flush()
        active = KnowledgeBaseRevision(kb_id=kb.id, revision=1, status="active", manifest_json={})
        candidate = KnowledgeBaseRevision(kb_id=kb.id, revision=2, status="candidate", manifest_json={})
        allowed_user = uuid.uuid4(); denied_user = uuid.uuid4()
        db.add_all([
            active, candidate,
            KnowledgeBaseMember(kb_id=kb.id, subject_type="user", subject_id=allowed_user, role="reader", effect="allow"),
        ]); db.flush()

        denied = AuthorizationContext(tenant_id=tenant.id, subject_id=denied_user)
        allowed = AuthorizationContext(tenant_id=tenant.id, subject_id=allowed_user)
        admin = AuthorizationContext(tenant_id=tenant.id, subject_id=denied_user, role_ids=["kb_admin"])
        assert resolve_kb_revision_scope(authz=denied, requested=None, db=db)["kb_revision_ids"] == []
        assert resolve_kb_revision_scope(
            authz=allowed, requested={"kb_revision_id": str(candidate.id)}, db=db
        )["kb_revision_ids"] == []
        assert resolve_kb_revision_scope(
            authz=admin, requested={"kb_revision_id": str(candidate.id)}, db=db
        )["kb_revision_ids"] == [str(candidate.id)]
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_gateway_hits_must_match_exact_visible_document_revision(client, superuser_headers, test_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.core.authorization import AuthorizationContext
    from app.gateway.contracts import ChunkResult
    from app.models.document import Document, DocumentChunk
    from app.models.kb_maintenance import DocumentVersion
    from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
    from app.models.knowledge_engine import KnowledgeBaseRevisionDocument
    from app.services.retrieval_facade import RetrievalFacade

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"]); subject_id = uuid.UUID(me["id"])
    db = sessionmaker(bind=test_engine)()
    try:
        document = Document(
            tenant_id=tenant_id, filename=f"gateway-{uuid.uuid4().hex}.txt",
            file_type="txt", status="completed", version=2,
        )
        kb = KnowledgeBase(tenant_id=tenant_id, name=f"Gateway-{uuid.uuid4().hex}", status="active")
        db.add_all([document, kb]); db.flush()
        version = DocumentVersion(
            tenant_id=tenant_id, document_id=document.id, version=1,
            filename=document.filename, status="completed", content_snapshot="v1",
        )
        revision = KnowledgeBaseRevision(kb_id=kb.id, revision=1, status="active", manifest_json={})
        db.add_all([version, revision]); db.flush()
        db.add(KnowledgeBaseRevisionDocument(
            tenant_id=tenant_id, kb_revision_id=revision.id,
            document_id=document.id, document_version_id=version.id,
            document_revision=1, content_hash="a" * 64, acl_snapshot={}, policy_revision=1,
        ))
        db.add(DocumentChunk(
            tenant_id=tenant_id,
            document_id=document.id,
            document_revision=1,
            chunk_index=0,
            text="v1",
            chunk_hash=uuid.uuid4().hex,
        ))
        _add_ready_profile(db, document, 1)
        db.flush()
        monkeypatch.setattr("app.services.document_visibility.deny_set_allows", lambda *_a, **_k: True)
        authz = AuthorizationContext(tenant_id=tenant_id, subject_id=subject_id, role_ids=["kb_admin"])
        results = [
            ChunkResult(id="old", content="v1", score=1, result_type="chunk", document_id=str(document.id), document_revision=1),
            ChunkResult(id="new", content="v2", score=1, result_type="chunk", document_id=str(document.id), document_revision=2),
            ChunkResult(id="external", content="unmapped", score=1, result_type="connector", document_id=None),
        ]
        kept = RetrievalFacade._filter_gateway_visibility(
            results, authz=authz, scope={"kb_revision_ids": [str(revision.id)]}, db=db,
        )
        assert [result.id for result in kept] == ["old"]
    finally:
        db.rollback(); db.close()


@pytest.mark.asyncio
async def test_document_head_cannot_cross_department_on_same_filename(client, superuser_headers, test_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.core.authorization import AuthorizationContext
    from app.models.document import Document, DocumentChunk
    from app.models.permission import Department
    from app.services.retrieval_facade import RetrievalFacade

    me = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()
    tenant_id = uuid.UUID(me["tenant_id"]); db = sessionmaker(bind=test_engine)()
    try:
        allowed_department = Department(tenant_id=tenant_id, name=f"Allowed-{uuid.uuid4().hex}")
        denied_department = Department(tenant_id=tenant_id, name=f"Denied-{uuid.uuid4().hex}")
        db.add_all([allowed_department, denied_department]); db.flush()
        filename = f"same-{uuid.uuid4().hex}.pdf"
        allowed_doc = Document(tenant_id=tenant_id, department_id=allowed_department.id, filename=filename, file_type="pdf", status="completed", version=1)
        denied_doc = Document(tenant_id=tenant_id, department_id=denied_department.id, filename=filename, file_type="pdf", status="completed", version=1)
        db.add_all([allowed_doc, denied_doc]); db.flush()
        db.add_all([
            DocumentChunk(tenant_id=tenant_id, document_id=allowed_doc.id, document_revision=1, chunk_index=0, text="可見內容", chunk_hash=uuid.uuid4().hex),
            DocumentChunk(tenant_id=tenant_id, document_id=denied_doc.id, document_revision=1, chunk_index=0, text="不可見內容", chunk_hash=uuid.uuid4().hex),
        ]); db.flush()
        monkeypatch.setattr("app.services.document_visibility.deny_set_allows", lambda *_a, **_k: True)
        authz = AuthorizationContext(
            tenant_id=tenant_id, subject_id=uuid.uuid4(), department_ids=[allowed_department.id],
        )
        from app.platform.knowledge import KnowledgeProviderRegistry

        rows = RetrievalFacade(
            providers=KnowledgeProviderRegistry()
        ).get_document_head(authz=authz, filename=filename, n=10, db=db)
        assert [row["content"] for row in rows] == ["可見內容"]
    finally:
        db.rollback(); db.close()
