"""Phase 2 任務引擎契約測試：版本化定義、idempotency、狀態機、handlers、provenance。"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.base_class import Base
from app.models.document import Document, DocumentChunk
from app.models.mka import (
    ApprovalPolicy,
    FormDefinition,
    FormInstance,
    InteractionSession,
    JobModule,
    JobRole,
    KnowhowCardModel,
    MKAApprovalRequest,
    TaskDefinition,
    TaskRun,
    TaskRunEvent,
    TenantModuleBinding,
    UserJobRoleAssignment,
)
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.services.mka_module_seed import seed_canonical_task_definitions
from app.services.task_engine import (
    TaskAccessDenied,
    TaskEngine,
    TaskEngineError,
    TaskHandlerNotImplemented,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Tenant.__table__, Department.__table__, User.__table__,
        JobModule.__table__, TenantModuleBinding.__table__,
        JobRole.__table__, UserJobRoleAssignment.__table__,
        TaskDefinition.__table__, TaskRun.__table__, TaskRunEvent.__table__,
        InteractionSession.__table__, FormDefinition.__table__,
        ApprovalPolicy.__table__, MKAApprovalRequest.__table__,
        FormInstance.__table__, KnowhowCardModel.__table__,
        Document.__table__, DocumentChunk.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db, role="employee"):
    tenant = Tenant(id=uuid.uuid4(), name=f"tenant-{uuid.uuid4()}")
    db.add(tenant)
    user = User(
        id=uuid.uuid4(), tenant_id=tenant.id,
        email=f"{uuid.uuid4()}@test.local", hashed_password="x", role=role,
    )
    db.add(user)
    db.commit()
    return tenant, user


def _sales_user(db):
    """有 sales 職能、sales_quote 模組已啟用的員工。"""
    from app.models.mka import JobModule, JobRole, TenantModuleBinding, UserJobRoleAssignment

    tenant, user = _user(db)
    db.add(JobModule(
        id=uuid.uuid4(), module_key="sales_quote", tenant_id=None,
        name="業務報價", status="enabled", allowed_roles=["employee", "owner", "admin"],
        allowed_job_role_keys=["sales"], form_definition_ids=["quote"],
    ))
    db.add(TenantModuleBinding(
        id=uuid.uuid4(), tenant_id=tenant.id, module_key="sales_quote",
        enabled=True, config_version=0,
    ))
    role = JobRole(
        id=uuid.uuid4(), tenant_id=tenant.id, role_key="sales", name="業務",
        default_module_keys=["sales_quote"], active=True,
    )
    db.add(role)
    db.commit()
    db.add(UserJobRoleAssignment(
        id=uuid.uuid4(), tenant_id=tenant.id, user_id=user.id,
        job_role_id=role.id, is_primary=True, active=True,
    ))
    db.commit()
    seed_canonical_task_definitions(db)
    db.commit()
    return tenant, user, role


class TestDefinitionResolution:
    def test_global_definition_resolved(self, db):
        tenant, _ = _user(db)
        seed_canonical_task_definitions(db)
        db.commit()
        engine = TaskEngine(db)
        d = engine.resolve_definition(tenant.id, "quote")
        assert d is not None
        assert d.task_key == "quote"
        assert d.version == "1.0"

    def test_tenant_override_wins(self, db):
        tenant, _ = _user(db)
        seed_canonical_task_definitions(db)
        db.add(TaskDefinition(
            id=uuid.uuid4(), tenant_id=tenant.id, task_key="quote",
            name="客製報價", version="1.0", status="enabled", handler_key="quote",
            module_key="sales_quote",
        ))
        db.commit()
        engine = TaskEngine(db)
        d = engine.resolve_definition(tenant.id, "quote")
        assert d.name == "客製報價"

    def test_latest_version_wins(self, db):
        tenant, _ = _user(db)
        db.add(TaskDefinition(
            id=uuid.uuid4(), tenant_id=None, task_key="x1",
            name="v1", version="1.0", status="enabled", handler_key="ask",
        ))
        db.add(TaskDefinition(
            id=uuid.uuid4(), tenant_id=None, task_key="x1",
            name="v2", version="2.0", status="enabled", handler_key="ask",
        ))
        db.commit()
        d = TaskEngine(db).resolve_definition(tenant.id, "x1")
        assert d.name == "v2"

    def test_unknown_task_returns_none(self, db):
        tenant, _ = _user(db)
        assert TaskEngine(db).resolve_definition(tenant.id, "nope") is None


class TestStartRun:
    def test_idempotency(self, db):
        tenant, user, _ = _sales_user(db)
        engine = TaskEngine(db)
        run1, created1 = engine.start_run(
            user=user, task_key="quote", idempotency_key="idem-00000001",
            inputs={"values": {"customer": "台中精機"}},
        )
        run2, created2 = engine.start_run(
            user=user, task_key="quote", idempotency_key="idem-00000001",
        )
        assert created1 is True
        assert created2 is False
        assert run1.id == run2.id

    def test_run_records_context_and_job_role(self, db):
        tenant, user, role = _sales_user(db)
        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=user, task_key="quote", idempotency_key="idem-00000002",
        )
        assert run.status == "draft"
        assert run.job_role_id == role.id
        assert run.module_key == "sales_quote"
        assert run.resolved_context["active_job_role"]["role_key"] == "sales"

    def test_unknown_task_rejected(self, db):
        tenant, user, _ = _sales_user(db)
        with pytest.raises(TaskEngineError, match="不存在"):
            TaskEngine(db).start_run(
                user=user, task_key="nope", idempotency_key="idem-00000003",
            )

    def test_missing_capability_denied(self, db):
        tenant, user, _ = _sales_user(db)
        user.role = "viewer"  # viewer 無 create_content（interview 需要）
        db.commit()
        with pytest.raises(TaskAccessDenied, match="缺少能力"):
            TaskEngine(db).start_run(
                user=user, task_key="interview", idempotency_key="idem-00000004",
            )

    def test_wrong_job_role_denied(self, db):
        tenant, user, role = _sales_user(db)
        role.role_key = "field"  # 不再是 sales
        db.commit()
        # 模組 allowlist 或任務職能限制其一必須擋下
        with pytest.raises(TaskAccessDenied):
            TaskEngine(db).start_run(
                user=user, task_key="quote", idempotency_key="idem-00000005",
            )


class TestStateMachine:
    def test_legal_transitions(self, db):
        tenant, user, _ = _sales_user(db)
        engine = TaskEngine(db)
        run, _ = engine.start_run(user=user, task_key="quote", idempotency_key="idem-00000010")
        engine.transition(run, "in_progress")
        engine.transition(run, "waiting_review")
        engine.transition(run, "approved")
        engine.transition(run, "executed")
        engine.transition(run, "exported")
        assert run.status == "exported"

    def test_illegal_transition_rejected(self, db):
        tenant, user, _ = _sales_user(db)
        engine = TaskEngine(db)
        run, _ = engine.start_run(user=user, task_key="quote", idempotency_key="idem-00000011")
        with pytest.raises(TaskEngineError, match="非法狀態轉換"):
            engine.transition(run, "approved")

    def test_terminal_status_no_transition(self, db):
        tenant, user, _ = _sales_user(db)
        engine = TaskEngine(db)
        run, _ = engine.start_run(user=user, task_key="quote", idempotency_key="idem-00000012")
        engine.transition(run, "in_progress")
        engine.fail(run, code="X", message="boom", retryable=True)
        assert run.status == "failed"
        assert run.error["code"] == "X"
        engine.transition(run, "draft")  # failed 可重來

    def test_rejected_returns_to_draft(self, db):
        tenant, user, _ = _sales_user(db)
        engine = TaskEngine(db)
        run, _ = engine.start_run(user=user, task_key="quote", idempotency_key="idem-00000013")
        engine.transition(run, "in_progress")
        engine.transition(run, "waiting_review")
        engine.transition(run, "rejected")
        engine.transition(run, "draft")
        assert run.status == "draft"


class TestHandlers:
    def test_quote_handler_creates_form_and_waits_review(self, db):
        tenant, user, _ = _sales_user(db)
        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=user, task_key="quote", idempotency_key="idem-00000020",
            inputs={
                "values": {"customer": "台中精機"},
                "sources": {"customer": {"source": "voice", "confidence": 0.9}},
            },
        )
        result = engine.execute(run, user)
        assert run.status == "waiting_review"
        assert result.output_refs["form_key"] == "quote"
        form = db.query(FormInstance).filter(
            FormInstance.id == uuid.UUID(result.output_refs["form_instance_id"])
        ).one()
        assert form.values_json["customer"] == "台中精機"
        assert run.field_sources["customer"]["source"] == "voice"
        assert run.provenance["handler"] == "quote"

    def test_interview_handler_creates_knowhow_draft(self, db):
        tenant, user = _user(db, role="owner")
        # interview 需要 master 職能 + training_knowhow 模組
        from app.models.mka import JobModule, JobRole, TenantModuleBinding, UserJobRoleAssignment

        db.add(JobModule(
            id=uuid.uuid4(), module_key="training_knowhow", tenant_id=None,
            name="訓練傳承", status="enabled", allowed_roles=["owner"],
            allowed_job_role_keys=["master"],
        ))
        db.add(TenantModuleBinding(
            id=uuid.uuid4(), tenant_id=tenant.id, module_key="training_knowhow",
            enabled=True, config_version=0,
        ))
        role = JobRole(
            id=uuid.uuid4(), tenant_id=tenant.id, role_key="master", name="師傅",
            default_module_keys=["training_knowhow"], active=True,
        )
        db.add(role)
        db.commit()
        db.add(UserJobRoleAssignment(
            id=uuid.uuid4(), tenant_id=tenant.id, user_id=user.id,
            job_role_id=role.id, is_primary=True, active=True,
        ))
        seed_canonical_task_definitions(db)
        db.commit()

        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=user, task_key="interview", idempotency_key="idem-00000021",
            inputs={"title": "換模技巧", "summary": "快速換模三步驟"},
        )
        result = engine.execute(run, user)
        assert run.status == "waiting_review"
        card = db.query(KnowhowCardModel).filter(
            KnowhowCardModel.id == uuid.UUID(result.output_refs["knowhow_card_id"])
        ).one()
        assert card.title == "換模技巧"
        assert card.status == "draft"

    def test_unimplemented_handler_fails_loudly(self, db):
        tenant, user, _ = _sales_user(db)
        # ask 掛在 spec_sop 模組下，補上模組與 binding 才能過存取檢查
        db.add(JobModule(
            id=uuid.uuid4(), module_key="spec_sop", tenant_id=None,
            name="規格查詢", status="enabled", allowed_roles=["employee"],
        ))
        db.add(TenantModuleBinding(
            id=uuid.uuid4(), tenant_id=tenant.id, module_key="spec_sop",
            enabled=True, config_version=0,
        ))
        db.commit()
        engine = TaskEngine(db)
        # ask 不限職能，但 handler 尚未實作
        run, _ = engine.start_run(
            user=user, task_key="ask", idempotency_key="idem-00000022",
            inputs={"question": "P-100 的扭力？"},
        )
        with pytest.raises(TaskHandlerNotImplemented):
            engine.execute(run, user)


class TestQuoteVerticalSlice:
    def test_knowledge_fill_and_rule_calc(self, db):
        """缺 unit_price → 知識補值；quantity×unit_price → 規則計算；缺欄位入 provenance。"""
        from app.models.document import Document, DocumentChunk

        tenant, user, _ = _sales_user(db)
        doc = Document(
            id=uuid.uuid4(), tenant_id=tenant.id, filename="price-list.txt",
            status="completed",
        )
        db.add(doc)
        db.add(DocumentChunk(
            id=uuid.uuid4(), tenant_id=tenant.id, document_id=doc.id,
            chunk_index=0, text="料號 P-100 單價：120 元",
        ))
        db.commit()

        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=user, task_key="quote", idempotency_key="idem-00000040",
            inputs={
                "values": {"customer": "台中精機", "part_number": "P-100", "quantity": 200},
                "sources": {"customer": {"source": "voice", "confidence": 0.9}},
            },
        )
        result = engine.execute(run, user)

        # 知識補值
        assert run.field_sources["unit_price"]["source"] == "knowledge"
        assert run.field_sources["unit_price"]["ref"].startswith("doc:")
        # 規則計算
        assert run.field_sources["subtotal"]["source"] == "rule"
        assert run.field_sources["total"]["source"] == "rule"
        form = db.query(FormInstance).filter(
            FormInstance.id == uuid.UUID(result.output_refs["form_instance_id"])
        ).one()
        assert form.values_json["unit_price"] == 120.0
        assert form.values_json["subtotal"] == 24000.0
        # 缺欄位（valid_until 等必填未填）
        assert "valid_until" in run.provenance["missing_fields"]
        assert run.status == "waiting_review"

    def test_no_knowledge_hit_stays_honest(self, db):
        """知識庫查不到價格時不編造，unit_price 維持缺值。"""
        tenant, user, _ = _sales_user(db)
        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=user, task_key="quote", idempotency_key="idem-00000041",
            inputs={"values": {"customer": "台中精機", "part_number": "NOPE-1", "quantity": 5}},
        )
        engine.execute(run, user)
        form = db.query(FormInstance).filter(
            FormInstance.id == uuid.UUID(run.output_refs["form_instance_id"])
        ).one()
        assert "unit_price" not in (form.values_json or {})
        assert "unit_price" in run.provenance["missing_fields"]


class TestExpandedHandlers:
    """Phase 6：現場／品質／傳承／訓練工作區的 handler。"""

    def _setup_role_module(self, db, *, role_key, module_key, forms):
        from app.models.mka import JobModule, JobRole, TenantModuleBinding, UserJobRoleAssignment

        tenant, user = _user(db)
        db.add(JobModule(
            id=uuid.uuid4(), module_key=module_key, tenant_id=None,
            name=module_key, status="enabled", allowed_roles=["employee"],
            allowed_job_role_keys=[role_key], form_definition_ids=forms,
        ))
        db.add(TenantModuleBinding(
            id=uuid.uuid4(), tenant_id=tenant.id, module_key=module_key,
            enabled=True, config_version=0,
        ))
        role = JobRole(
            id=uuid.uuid4(), tenant_id=tenant.id, role_key=role_key, name=role_key,
            default_module_keys=[module_key], active=True,
        )
        db.add(role)
        db.commit()
        db.add(UserJobRoleAssignment(
            id=uuid.uuid4(), tenant_id=tenant.id, user_id=user.id,
            job_role_id=role.id, is_primary=True, active=True,
        ))
        db.commit()
        seed_canonical_task_definitions(db)
        db.commit()
        return tenant, user

    @pytest.mark.parametrize(
        ("task_key", "module_key", "forms"),
        [
            ("quote", "sales_quote", ["quote"]),
            ("incident", "incident_handover", ["incident_report"]),
            ("handover", "incident_handover", ["shift_handover"]),
            ("daily_report", "incident_handover", ["daily_report"]),
            ("quality_8d", "quality_8d", ["quality_8d"]),
            ("training", "training_knowhow", ["training_checklist"]),
            ("interview", "training_knowhow", []),
        ],
    )
    def test_supervisor_can_start_cross_functional_workspace_tasks(
        self, db, task_key, module_key, forms
    ):
        _, user = self._setup_role_module(
            db, role_key="supervisor", module_key=module_key, forms=forms,
        )
        run, created = TaskEngine(db).start_run(
            user=user,
            task_key=task_key,
            idempotency_key=f"supervisor-{task_key}-0001",
        )
        assert created is True
        assert run.task_key == task_key

    def test_newcomer_discovery_hides_interview_task(self, db):
        _, user = self._setup_role_module(
            db,
            role_key="newcomer",
            module_key="training_knowhow",
            forms=["training_checklist"],
        )
        keys = {
            definition.task_key
            for definition in TaskEngine(db).list_accessible_definitions(user)
        }
        assert "training" in keys
        assert "interview" not in keys

    def test_training_handler_creates_checklist(self, db):
        tenant, user = self._setup_role_module(
            db, role_key="newcomer", module_key="training_knowhow",
            forms=["training_checklist"],
        )
        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=user, task_key="training", idempotency_key="idem-00000050",
            inputs={"values": {"trainee": "小美", "job_role": "作業員",
                               "required_docs": "SOP-001", "mentor": "老王"}},
        )
        result = engine.execute(run, user)
        assert run.status == "waiting_review"
        form = db.query(FormInstance).filter(
            FormInstance.id == uuid.UUID(result.output_refs["form_instance_id"])
        ).one()
        assert form.values_json["trainee"] == "小美"

    def test_daily_report_handler(self, db):
        tenant, user = self._setup_role_module(
            db, role_key="field", module_key="incident_handover",
            forms=["daily_report"],
        )
        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=user, task_key="daily_report", idempotency_key="idem-00000051",
            inputs={"values": {"report_date": "2026-08-07", "shift": "早班",
                               "line": "A線", "work_summary": "換模與點檢"}},
        )
        result = engine.execute(run, user)
        assert result.output_refs["form_key"] == "daily_report"
        assert run.status == "waiting_review"

    def test_handover_handler_via_task(self, db):
        tenant, user = self._setup_role_module(
            db, role_key="field", module_key="incident_handover",
            forms=["shift_handover"],
        )
        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=user, task_key="handover", idempotency_key="idem-00000052",
            inputs={"values": {"shift_date": "2026-08-07", "shift": "早班",
                               "line": "A線", "outgoing": "阿明", "incoming": "阿華",
                               "production_summary": "正常"}},
        )
        result = engine.execute(run, user)
        assert result.output_refs["form_key"] == "shift_handover"


class TestObservability:
    """Phase 7：事件流與指標。"""

    def test_events_recorded(self, db):
        from app.models.mka import TaskRunEvent

        tenant, user, _ = _sales_user(db)
        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=user, task_key="quote", idempotency_key="idem-00000060",
            inputs={"values": {"customer": "台中精機"}},
        )
        engine.record_field_sources(run, {"customer": {"source": "voice", "confidence": 0.9}})
        engine.record_manual_edit(run, "customer")
        engine.execute(run, user)

        events = (
            db.query(TaskRunEvent)
            .filter(TaskRunEvent.run_id == run.id)
            .all()
        )
        types = [e.event_type for e in events]
        assert "run_created" in types
        assert "field_sources_updated" in types
        assert "manual_edit" in types
        assert "transition" in types
        assert "executed" in types

    def test_metrics_summary(self, db):
        from app.services.task_metrics import compute_task_metrics

        tenant, user, _ = _sales_user(db)
        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=user, task_key="quote", idempotency_key="idem-00000061",
            inputs={"values": {"customer": "台中精機"}},
        )
        engine.record_field_sources(run, {"customer": {"source": "voice"}})
        engine.record_manual_edit(run, "customer")
        engine.execute(run, user)

        m = compute_task_metrics(db, tenant.id)
        assert m["total_runs"] == 1
        assert m["by_status"]["waiting_review"] == 1
        assert m["completion_rate"] == 1.0
        assert m["error_rate"] == 0.0
        assert m["manual_edit_rate"] == 1.0
        assert m["field_source_distribution"]["voice"] == 1
        assert m["event_count"] >= 4


class TestProvenance:
    def test_field_sources_and_manual_edits(self, db):
        tenant, user, _ = _sales_user(db)
        engine = TaskEngine(db)
        run, _ = engine.start_run(user=user, task_key="quote", idempotency_key="idem-00000030")
        engine.record_field_sources(run, {
            "unit_price": {"source": "knowledge", "ref": "doc:price-list-v3", "confidence": 0.85},
        })
        engine.record_manual_edit(run, "unit_price")
        engine.record_manual_edit(run, "unit_price")  # 不重複
        engine.record_manual_edit(run, "quantity")
        assert run.field_sources["unit_price"]["ref"] == "doc:price-list-v3"
        assert run.provenance["manual_edits"] == ["unit_price", "quantity"]
