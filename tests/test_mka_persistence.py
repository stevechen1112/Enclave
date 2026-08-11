"""Focused MKA DB persistence contract tests (no process-memory substitutes)."""
import uuid
import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationship targets
from app.db.base_class import Base
from app.models.mka import (
    ApprovalPolicy,
    FormDefinition,
    FormInstance,
    InteractionSession,
    KnowhowCardModel,
    MKAApprovalRequest,
)
from app.models.document import Document, DocumentChunk
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.core.authorization import AuthorizationContext
from app.services.mka_persistence import (
    MKAConflictError,
    MKAForbiddenError,
    MKAPersistenceError,
    MKARepository,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Tenant.__table__,
        Department.__table__,
        User.__table__,
        InteractionSession.__table__,
        FormDefinition.__table__,
        ApprovalPolicy.__table__,
        MKAApprovalRequest.__table__,
        FormInstance.__table__,
        KnowhowCardModel.__table__,
        # SOP 衝突檢查會真實查詢 Document／DocumentChunk，測試庫必須建表
        Document.__table__,
        DocumentChunk.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _identity(db, role="owner"):
    tenant = Tenant(id=uuid.uuid4(), name=f"tenant-{uuid.uuid4()}")
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"{uuid.uuid4()}@test.local",
        hashed_password="not-used",
        role=role,
        status="active",
    )
    db.add_all([tenant, user])
    db.flush()
    return tenant, user


def _valid_quote():
    return {
        "customer": "ACME",
        "part_number": "P-100",
        "quantity": 2,
        "unit_price": 100.0,
        "tax_rate": 5,
        "valid_until": "2026-12-31",
        "payment_terms": "現金",
    }


def test_tenant_filtering_and_draft_isolation(db):
    tenant_a, _ = _identity(db)
    tenant_b, _ = _identity(db)
    repo = MKARepository(db)
    approved = repo.create_knowhow(
        tenant_id=tenant_a.id, title="approved", steps=["a"]
    )
    draft = repo.create_knowhow(tenant_id=tenant_a.id, title="draft", steps=["b"])
    other = repo.create_knowhow(tenant_id=tenant_b.id, title="other", steps=["c"])
    approved.status = "approved"
    other.status = "approved"
    db.flush()

    assert {row.id for row in repo.list_knowhow(tenant_id=tenant_a.id)} == {
        draft.id,
        approved.id,
    }
    assert [row.id for row in repo.list_approved_knowhow(tenant_id=tenant_a.id)] == [
        approved.id
    ]


def test_retrieval_facade_injects_only_tenant_approved_db_cards(db, monkeypatch):
    tenant_a, user_a = _identity(db)
    tenant_b, _ = _identity(db)
    repo = MKARepository(db)
    approved = repo.create_knowhow(
        tenant_id=tenant_a.id,
        title="approved-a",
        steps=["a"],
        data={"source_document_id": "legacy-a"},
    )
    draft = repo.create_knowhow(
        tenant_id=tenant_a.id,
        title="draft-a",
        steps=["b"],
        data={"source_document_id": "legacy-b"},
    )
    other = repo.create_knowhow(
        tenant_id=tenant_b.id,
        title="approved-b",
        steps=["c"],
        data={"source_document_id": "legacy-c"},
    )
    approved.status = "approved"
    other.status = "approved"
    db.flush()

    from app.config import settings
    from app.services.kb_retrieval import KnowledgeBaseRetriever
    from app.services.retrieval_facade import RetrievalFacade

    monkeypatch.setattr(settings, "KNOWHOW_CARD_ENABLED", True)
    monkeypatch.setattr(settings, "KNOWHOW_DRAFT_ISOLATION", True)
    monkeypatch.setattr(KnowledgeBaseRetriever, "search", lambda *args, **kwargs: [])
    result = RetrievalFacade().search(
        authz=AuthorizationContext.from_user(user_a),
        query="know-how",
        db=db,
    )
    ids = {row["id"] for row in result.results}
    assert f"knowhow:{approved.card_id}" in ids
    assert f"knowhow:{draft.card_id}" not in ids
    assert f"knowhow:{other.card_id}" not in ids


def test_form_optimistic_lock_and_immutable_snapshot(db):
    tenant, user = _identity(db)
    repo = MKARepository(db)
    form = repo.create_form_instance(
        tenant_id=tenant.id,
        owner_id=user.id,
        form_key="quote",
        values=_valid_quote(),
        provenance={"customer": {"source": "voice", "session_id": "s-1"}},
    )
    db.flush()

    updated = repo.patch_form_instance(
        tenant_id=tenant.id,
        instance_id=form.id,
        actor_id=user.id,
        expected_version=1,
        values={"quantity": 3},
    )
    assert updated.record_version == 2
    with pytest.raises(MKAConflictError, match="stale record_version"):
        repo.patch_form_instance(
            tenant_id=tenant.id,
            instance_id=form.id,
            actor_id=user.id,
            expected_version=1,
            values={"quantity": 4},
        )

    form, approval = repo.submit_form(
        tenant_id=tenant.id,
        instance_id=form.id,
        submitted_by=user.id,
        expected_version=2,
        idempotency_key="quote-submit-1",
    )
    assert form.status == "pending_review"
    assert form.immutable_snapshot == approval.immutable_snapshot
    assert form.immutable_snapshot["values"]["subtotal"] == 300.0
    with pytest.raises(MKAConflictError, match="immutable"):
        repo.patch_form_instance(
            tenant_id=tenant.id,
            instance_id=form.id,
            actor_id=user.id,
            expected_version=form.record_version,
            values={"quantity": 999},
        )


def test_multi_step_approval_and_stale_reject(db):
    tenant, owner = _identity(db, role="owner")
    admin = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"{uuid.uuid4()}@test.local",
        hashed_password="not-used",
        role="admin",
        status="active",
    )
    db.add(admin)
    repo = MKARepository(db)
    form = repo.create_form_instance(
        tenant_id=tenant.id,
        owner_id=owner.id,
        form_key="quote",
        values=_valid_quote(),
    )
    definition = (
        db.query(FormDefinition)
        .filter(
            FormDefinition.tenant_id == tenant.id,
            FormDefinition.id == form.form_definition_id,
        )
        .one()
    )
    policy = (
        db.query(ApprovalPolicy)
        .filter(
            ApprovalPolicy.tenant_id == tenant.id,
            ApprovalPolicy.id == definition.approval_policy_id,
        )
        .one()
    )
    policy.steps = [
        {"name": "owner_review", "roles": ["owner"]},
        {"name": "admin_review", "roles": ["admin"]},
    ]
    db.flush()
    form, approval = repo.submit_form(
        tenant_id=tenant.id,
        instance_id=form.id,
        submitted_by=owner.id,
        expected_version=1,
        idempotency_key="multi-step-1",
    )

    approval = repo.decide_approval(
        tenant_id=tenant.id,
        approval_id=approval.id,
        reviewer_id=owner.id,
        reviewer_roles=["owner"],
        expected_version=1,
        idempotency_key="decision-owner-1",
        action="approve",
    )
    assert approval.status == "pending"
    assert approval.current_step == 1
    assert len(approval.decision_log) == 1
    with pytest.raises(MKAConflictError, match="stale record_version"):
        repo.decide_approval(
            tenant_id=tenant.id,
            approval_id=approval.id,
            reviewer_id=admin.id,
            reviewer_roles=["admin"],
            expected_version=1,
            idempotency_key="decision-admin-stale",
            action="approve",
        )
    approval = repo.decide_approval(
        tenant_id=tenant.id,
        approval_id=approval.id,
        reviewer_id=admin.id,
        reviewer_roles=["admin"],
        expected_version=2,
        idempotency_key="decision-admin-1",
        action="approve",
    )
    assert approval.status == "approved"
    assert len(approval.decision_log) == 2
    assert form.status == "approved"


def test_form_owner_admin_authorization_and_submit_owner_only(db):
    tenant, owner = _identity(db, role="employee")
    _, outsider = _identity(db, role="employee")
    outsider.tenant_id = tenant.id
    admin = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"{uuid.uuid4()}@test.local",
        hashed_password="not-used",
        role="admin",
        status="active",
    )
    db.add(admin)
    repo = MKARepository(db)
    form = repo.create_form_instance(
        tenant_id=tenant.id,
        owner_id=owner.id,
        form_key="quote",
        values=_valid_quote(),
    )
    with pytest.raises(MKAForbiddenError, match="owner, admin"):
        repo.get_form_instance(
            tenant_id=tenant.id,
            instance_id=form.id,
            actor_id=outsider.id,
            actor_roles=["employee"],
        )
    assert (
        repo.get_form_instance(
            tenant_id=tenant.id,
            instance_id=form.id,
            actor_id=admin.id,
            actor_roles=["admin"],
        ).id
        == form.id
    )
    repo.patch_form_instance(
        tenant_id=tenant.id,
        instance_id=form.id,
        actor_id=admin.id,
        actor_roles=["admin"],
        expected_version=1,
        values={"quantity": 3},
    )
    with pytest.raises(MKAForbiddenError, match="only the form owner"):
        repo.submit_form(
            tenant_id=tenant.id,
            instance_id=form.id,
            submitted_by=admin.id,
            expected_version=2,
            idempotency_key="admin-submit-denied",
        )


def test_form_and_approval_mutations_use_row_locks():
    form_source = inspect.getsource(MKARepository._get_form_instance)
    approval_source = inspect.getsource(MKARepository._get_approval)
    assert "with_for_update()" in form_source
    assert "with_for_update()" in approval_source


def test_form_endpoints_forward_actor_context_and_request_defaults_are_isolated():
    import app.api.v1.endpoints.forms as forms_endpoint
    from app.api.v1.endpoints.knowhow import KnowhowCreateRequest
    from app.api.v1.endpoints.voice import TranscriptConfirmRequest

    source = inspect.getsource(forms_endpoint)
    assert source.count("**_actor_kwargs(current_user)") >= 4
    assert "submitted_by=current_user.id" in source

    form_a = forms_endpoint.FormCreateRequest()
    form_b = forms_endpoint.FormCreateRequest()
    form_a.values["x"] = 1
    assert form_b.values == {}
    knowhow_a = KnowhowCreateRequest(title="a")
    knowhow_b = KnowhowCreateRequest(title="b")
    knowhow_a.steps.append("step")
    assert knowhow_b.steps == []
    confirm_a = TranscriptConfirmRequest()
    confirm_b = TranscriptConfirmRequest()
    confirm_a.confirmed_fields["part"] = "P-1"
    assert confirm_b.confirmed_fields == {}


def test_approval_decision_idempotency_and_conflicting_reuse(db):
    tenant, owner = _identity(db, role="owner")
    repo = MKARepository(db)
    form = repo.create_form_instance(
        tenant_id=tenant.id,
        owner_id=owner.id,
        form_key="quote",
        values=_valid_quote(),
    )
    form, approval = repo.submit_form(
        tenant_id=tenant.id,
        instance_id=form.id,
        submitted_by=owner.id,
        expected_version=1,
        idempotency_key="submit-idem",
    )
    first = repo.decide_approval(
        tenant_id=tenant.id,
        approval_id=approval.id,
        reviewer_id=owner.id,
        reviewer_roles=["owner"],
        expected_version=1,
        idempotency_key="decision-idem",
        action="approve",
        reason="ok",
    )
    first_version = first.record_version
    first_log_size = len(first.decision_log)
    retry = repo.decide_approval(
        tenant_id=tenant.id,
        approval_id=approval.id,
        reviewer_id=owner.id,
        reviewer_roles=["owner"],
        expected_version=1,
        idempotency_key="decision-idem",
        action="approve",
        reason="ok",
    )
    assert retry.record_version == first_version
    assert len(retry.decision_log) == first_log_size
    assert retry.decision_log[0]["idempotency_key"] == "decision-idem"
    with pytest.raises(MKAConflictError, match="different content"):
        repo.decide_approval(
            tenant_id=tenant.id,
            approval_id=approval.id,
            reviewer_id=owner.id,
            reviewer_roles=["owner"],
            expected_version=first_version,
            idempotency_key="decision-idem",
            action="approve",
            reason="changed",
        )


def test_request_changes_and_reject_clear_form_submission_state(db):
    tenant, owner = _identity(db, role="owner")
    repo = MKARepository(db)
    form = repo.create_form_instance(
        tenant_id=tenant.id,
        owner_id=owner.id,
        form_key="quote",
        values=_valid_quote(),
    )
    form, approval = repo.submit_form(
        tenant_id=tenant.id,
        instance_id=form.id,
        submitted_by=owner.id,
        expected_version=1,
        idempotency_key="submit-before-changes",
    )
    repo.decide_approval(
        tenant_id=tenant.id,
        approval_id=approval.id,
        reviewer_id=owner.id,
        reviewer_roles=["owner"],
        expected_version=1,
        idempotency_key="request-changes-1",
        action="request_changes",
    )
    assert form.status == "changes_requested"
    assert form.approval_request_id is None
    assert form.immutable_snapshot == {}
    repo.patch_form_instance(
        tenant_id=tenant.id,
        instance_id=form.id,
        actor_id=owner.id,
        expected_version=form.record_version,
        values={"quantity": 4},
    )
    form, second = repo.submit_form(
        tenant_id=tenant.id,
        instance_id=form.id,
        submitted_by=owner.id,
        expected_version=form.record_version,
        idempotency_key="resubmit-after-changes",
    )
    assert form.approval_request_id == second.id
    repo.decide_approval(
        tenant_id=tenant.id,
        approval_id=second.id,
        reviewer_id=owner.id,
        reviewer_roles=["owner"],
        expected_version=1,
        idempotency_key="reject-1",
        action="reject",
    )
    assert form.status == "rejected"
    assert form.approval_request_id is None
    assert form.immutable_snapshot == {}


@pytest.mark.asyncio
async def test_chat_call_chain_forwards_request_db_to_retrieval(db, monkeypatch):
    tenant, user = _identity(db)
    seen = []

    class FakeFacade:
        def search_catalog(self, *, db=None, **kwargs):
            seen.append(db)
            return []

        async def search_gateway(self, *, db=None, **kwargs):
            from app.services.retrieval_facade import RetrievalResult

            seen.append(db)
            return RetrievalResult(
                results=[
                    {
                        "id": "chunk-1",
                        "document_id": "legacy-doc",
                        "content": "維修證據",
                        "score": 1.0,
                        "filename": "manual.pdf",
                    }
                ],
                citations=[],
                total=1,
            )

    import app.services.retrieval_facade as retrieval_module
    from app.services.chat_orchestrator import ChatOrchestrator

    monkeypatch.setattr(retrieval_module, "get_retrieval_facade", lambda: FakeFacade())
    orchestrator = object.__new__(ChatOrchestrator)
    await orchestrator.retrieve_context(
        tenant_id=tenant.id,
        question="如何維修機台",
        authz=AuthorizationContext.from_user(user),
        db=db,
    )
    assert seen
    assert all(item is db for item in seen)


def test_voice_transcript_persistence_and_high_risk_confirmation(db):
    tenant, user = _identity(db)
    repo = MKARepository(db)
    row = repo.save_transcript(
        tenant_id=tenant.id,
        user_id=user.id,
        text="料號 P-100，數量 2",
        metadata={
            "provider": "test",
            "segments": [{"start": 0, "end": 1, "text": "料號 P-100"}],
        },
        detected_fields=[
            {"type": "part_number", "value": "P-100", "needs_confirm": True}
        ],
        risk_level="high",
    )
    assert row.transcript_metadata["segments"][0]["text"] == "料號 P-100"
    with pytest.raises(MKAConflictError, match="must be confirmed"):
        repo.resolve_interaction(
            tenant_id=tenant.id, user_id=user.id, session_id=row.id
        )
    repo.confirm_transcript(
        tenant_id=tenant.id,
        user_id=user.id,
        session_id=row.id,
        confirmed_fields={"part_number": "P-100"},
    )
    resolved = repo.resolve_interaction(
        tenant_id=tenant.id, user_id=user.id, session_id=row.id
    )
    assert resolved.state == "completed"


def test_knowhow_submit_blocks_unresolved_sop_conflict(db):
    tenant, user = _identity(db)
    repo = MKARepository(db)
    card = repo.create_knowhow(
        tenant_id=tenant.id,
        title="unsafe draft",
        data={"conflict_report": [{"type": "step_mismatch", "resolved": False}]},
        owner_id=user.id,
    )
    with pytest.raises(MKAConflictError, match="unresolved SOP conflicts"):
        repo.submit_knowhow(
            tenant_id=tenant.id,
            knowhow_id=card.id,
            submitted_by=user.id,
            expected_version=1,
            idempotency_key="knowhow-submit-1",
        )


def test_approved_form_export_uses_immutable_snapshot(db):
    tenant, owner = _identity(db, role="owner")
    repo = MKARepository(db)
    form = repo.create_form_instance(
        tenant_id=tenant.id,
        owner_id=owner.id,
        form_key="quote",
        values=_valid_quote(),
    )
    for status in ("draft", "pending_review"):
        with pytest.raises(MKAConflictError, match="not approved"):
            repo.export_form(
                tenant_id=tenant.id,
                instance_id=form.id,
                actor_id=owner.id,
                format="md",
            )
        if status == "draft":
            form, approval = repo.submit_form(
                tenant_id=tenant.id,
                instance_id=form.id,
                submitted_by=owner.id,
                expected_version=1,
                idempotency_key="export-submit",
            )
    repo.decide_approval(
        tenant_id=tenant.id,
        approval_id=approval.id,
        reviewer_id=owner.id,
        reviewer_roles=["owner"],
        expected_version=1,
        idempotency_key="export-approve",
        action="approve",
    )
    assert form.status == "approved"
    result = repo.export_form(
        tenant_id=tenant.id,
        instance_id=form.id,
        actor_id=owner.id,
        format="md",
    )
    assert result.success
    content = result.content.decode("utf-8")
    assert "ACME" in content
    assert "Version" in content
    assert result.filename.endswith(".md")
    assert form.export_artifacts[-1]["format"] == "md"
    assert form.export_artifacts[-1]["exported_by"] == str(owner.id)
    with pytest.raises(MKAPersistenceError, match="unsupported export format"):
        repo.export_form(
            tenant_id=tenant.id,
            instance_id=form.id,
            actor_id=owner.id,
            format="exe",
        )


def test_form_export_endpoint_registered_with_actor_context():
    import inspect as _inspect

    import app.api.v1.endpoints.forms as forms_endpoint

    source = _inspect.getsource(forms_endpoint)
    assert '"/forms/instances/{instance_id}/export"' in source
    assert "export_form(" in source
    assert source.count("**_actor_kwargs(current_user)") >= 5


def test_knowhow_list_queries_are_bounded(db):
    tenant, user = _identity(db)
    repo = MKARepository(db)
    for i in range(5):
        card = repo.create_knowhow(
            tenant_id=tenant.id, title=f"card-{i}", steps=["s"]
        )
        card.status = "approved"
    db.flush()
    assert len(repo.list_knowhow(tenant_id=tenant.id)) == 5
    assert len(repo.list_knowhow(tenant_id=tenant.id, limit=3)) == 3
    assert len(repo.list_approved_knowhow(tenant_id=tenant.id, limit=2)) == 2
    src = inspect.getsource(MKARepository.list_approved_knowhow)
    assert ".limit(" in src


def test_voice_endpoint_enforces_upload_cap_duration_and_metrics():
    import app.api.v1.endpoints.voice as voice_endpoint

    source = inspect.getsource(voice_endpoint)
    assert "VOICE_MAX_AUDIO_BYTES" in source
    assert "status_code=413" in source
    assert "VOICE_MAX_AUDIO_SECONDS" in source
    assert "record_mka_stt" in source


def _approved_quote(db):
    """建立並核准一張報價單，回傳 (tenant, owner, form)。"""
    tenant, owner = _identity(db, role="owner")
    repo = MKARepository(db)
    form = repo.create_form_instance(
        tenant_id=tenant.id,
        owner_id=owner.id,
        form_key="quote",
        values=_valid_quote(),
    )
    form, approval = repo.submit_form(
        tenant_id=tenant.id,
        instance_id=form.id,
        submitted_by=owner.id,
        expected_version=1,
        idempotency_key=f"submit-{uuid.uuid4()}",
    )
    repo.decide_approval(
        tenant_id=tenant.id,
        approval_id=approval.id,
        reviewer_id=owner.id,
        reviewer_roles=["owner"],
        expected_version=1,
        idempotency_key=f"approve-{uuid.uuid4()}",
        action="approve",
    )
    return tenant, owner, form


def test_assert_form_exportable_pre_check(db):
    tenant, owner = _identity(db, role="owner")
    repo = MKARepository(db)
    form = repo.create_form_instance(
        tenant_id=tenant.id,
        owner_id=owner.id,
        form_key="quote",
        values=_valid_quote(),
    )
    with pytest.raises(MKAConflictError, match="not approved"):
        repo.assert_form_exportable(
            tenant_id=tenant.id, instance_id=form.id, actor_id=owner.id
        )
    tenant2, owner2, approved = _approved_quote(db)
    row = MKARepository(db).assert_form_exportable(
        tenant_id=tenant2.id, instance_id=approved.id, actor_id=owner2.id
    )
    assert row.status == "approved"


def test_render_form_export_task_stores_artifact(db, tmp_path, monkeypatch):
    import app.services.rls as rls_module
    import app.tasks.mka_tasks as mka_tasks
    from app.config import settings
    from app.services import storage as storage_module

    tenant, owner, form = _approved_quote(db)
    tenant_id_s, owner_id_s, form_id = str(tenant.id), str(owner.id), form.id
    monkeypatch.setattr(mka_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(rls_module, "apply_rls_context", lambda *a, **k: None)
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    storage_module.reset_storage_backend()
    try:
        result = mka_tasks.render_form_export(
            tenant_id_s, str(form_id), owner_id_s, "md", export_task_id="test-export-job"
        )
        assert result["storage_key"].startswith(f"{tenant_id_s}/")
        assert (tmp_path / result["storage_key"]).exists()
        # task 內 commit/close 過 session，重新查詢而非沿用舊 ORM 物件
        reloaded = MKARepository(db).get_form_instance(
            tenant_id=uuid.UUID(tenant_id_s),
            instance_id=form_id,
            actor_id=uuid.UUID(owner_id_s),
        )
        latest = reloaded.export_artifacts[-1]
        assert latest["storage_key"] == result["storage_key"]
        assert latest["status"] == "completed"
        assert latest["task_id"] == "test-export-job"
        content = storage_module.get_storage_backend().get_bytes(result["storage_key"])
        assert "ACME".encode("utf-8") in content
    finally:
        storage_module.reset_storage_backend()


def test_form_async_export_endpoints_registered():
    import app.api.v1.endpoints.forms as forms_endpoint

    source = inspect.getsource(forms_endpoint)
    assert "async_export" in source
    assert "render_form_export.delay" in source
    assert "JSONResponse" in source
    assert "status_code=202" in source
    assert '"/forms/instances/{instance_id}/exports"' in source
    assert '"/forms/instances/{instance_id}/exports/{artifact_index}/download"' in source
    assert "assert_key_matches_tenant" in source
