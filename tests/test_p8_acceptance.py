"""職能任務平台重構 Phase 8 驗收測試。

涵蓋可在程式內驗證的部分：
- 三個 demo 劇本的端到端 service-level 流程（報價垂直切片全鏈路）
- 第二租戶隔離（opt-in、定義覆寫不外洩、run 隔離）
- 任務層角色 ACL 矩陣

真語音 provider、真人 UX session、漸進上線屬環境驗收，
見 docs/runbooks/PHASE8_VERIFICATION.md。
"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
from app.services.mka_persistence import MKARepository
from app.services.task_engine import TaskAccessDenied, TaskEngine


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


def _tenant(db, name):
    t = Tenant(id=uuid.uuid4(), name=name)
    db.add(t)
    db.commit()
    return t


def _user(db, tenant, email, role="employee"):
    u = User(
        id=uuid.uuid4(), tenant_id=tenant.id, email=email,
        hashed_password="x", role=role,
    )
    db.add(u)
    db.commit()
    return u


def _bind(db, tenant, module_key, *, allowed_job_role_keys=None, forms=None):
    db.add(JobModule(
        id=uuid.uuid4(), module_key=module_key, tenant_id=None,
        name=module_key, status="enabled", allowed_roles=["employee", "admin"],
        allowed_job_role_keys=allowed_job_role_keys or [],
        form_definition_ids=forms or [],
    ))
    db.add(TenantModuleBinding(
        id=uuid.uuid4(), tenant_id=tenant.id, module_key=module_key,
        enabled=True, config_version=0,
    ))
    db.commit()


def _assign(db, tenant, user, role_key, module_keys):
    role = JobRole(
        id=uuid.uuid4(), tenant_id=tenant.id, role_key=role_key, name=role_key,
        default_module_keys=module_keys, active=True,
    )
    db.add(role)
    db.commit()
    db.add(UserJobRoleAssignment(
        id=uuid.uuid4(), tenant_id=tenant.id, user_id=user.id,
        job_role_id=role.id, is_primary=True, active=True,
    ))
    db.commit()
    return role


class TestQuoteEndToEnd:
    """劇本一：語音/文字報價 → 知識補值 → 規則計算 → 送審 → 核准 → 匯出。"""

    def test_full_quote_journey(self, db):
        tenant = _tenant(db, "Demo")
        sales = _user(db, tenant, "sales@demo.com")
        admin = _user(db, tenant, "admin@demo.com", role="admin")
        _bind(db, tenant, "sales_quote",
              allowed_job_role_keys=["sales"], forms=["quote"])
        _assign(db, tenant, sales, "sales", ["sales_quote"])
        seed_canonical_task_definitions(db)
        db.commit()

        # 知識庫有料號價格
        doc = Document(id=uuid.uuid4(), tenant_id=tenant.id,
                       filename="price.txt", status="completed")
        db.add(doc)
        db.add(DocumentChunk(
            id=uuid.uuid4(), tenant_id=tenant.id, document_id=doc.id,
            chunk_index=0, text="料號 P-100 單價：120 元",
        ))
        db.commit()

        engine = TaskEngine(db)
        # 1. 開任務（語音帶入部分欄位）
        run, created = engine.start_run(
            user=sales, task_key="quote", idempotency_key="p8-quote-001",
            inputs={
                "values": {"customer": "台中精機", "part_number": "P-100", "quantity": 200},
                "sources": {"customer": {"source": "voice", "confidence": 0.9}},
            },
        )
        assert created is True
        # 冪等：同 key 不重複建
        run2, created2 = engine.start_run(
            user=sales, task_key="quote", idempotency_key="p8-quote-001",
        )
        assert created2 is False and run2.id == run.id

        # 2. 執行：知識補值 + 規則計算 + 缺欄位
        result = engine.execute(run, sales)
        assert run.status == "in_progress"
        assert run.field_sources["unit_price"]["source"] == "knowledge"
        assert run.field_sources["subtotal"]["source"] == "rule"
        assert "valid_until" in run.provenance["missing_fields"]

        # 3. 表單送審 → 核准 → 匯出守衛
        repo = MKARepository(db)
        form_id = uuid.UUID(result.output_refs["form_instance_id"])
        form = repo.get_form_instance(
            tenant_id=tenant.id, instance_id=form_id,
            actor_id=sales.id, actor_roles=["employee"],
        )
        assert form.values_json["subtotal"] == 24000.0
        # 未核准不可匯出（guarded action）
        from app.services.mka_persistence import MKAConflictError
        with pytest.raises(MKAConflictError, match="not approved"):
            repo.assert_form_exportable(
                tenant_id=tenant.id, instance_id=form_id,
                actor_id=sales.id, actor_roles=["employee"],
            )

    def test_returned_quote_resumes_same_task_and_can_be_approved(self, db):
        tenant = _tenant(db, "Review lifecycle")
        sales = _user(db, tenant, "sales@review.example")
        owner = _user(db, tenant, "owner@review.example", role="owner")
        _bind(db, tenant, "sales_quote", allowed_job_role_keys=["sales"], forms=["quote"])
        _assign(db, tenant, sales, "sales", ["sales_quote"])
        seed_canonical_task_definitions(db)
        db.commit()

        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=sales,
            task_key="quote",
            idempotency_key="p8-review-lifecycle-001",
            inputs={
                "values": {
                    "customer": "Review customer",
                    "part_number": "P-100",
                    "quantity": 2,
                    "unit_price": 1200,
                    "valid_until": "2026-12-31",
                    "payment_terms": "月結30天",
                },
            },
        )
        first = engine.execute(run, sales)
        assert run.status == "waiting_review"
        first_form_id = uuid.UUID(first.output_refs["form_instance_id"])
        first_approval_id = uuid.UUID(first.output_refs["approval_id"])

        repo = MKARepository(db)
        repo.decide_approval(
            tenant_id=tenant.id,
            approval_id=first_approval_id,
            reviewer_id=owner.id,
            reviewer_roles=["owner"],
            expected_version=1,
            idempotency_key="p8-review-return-001",
            action="request_changes",
            reason="Please correct the quantity",
        )
        db.commit()
        db.refresh(run)
        assert run.status == "rejected"
        assert run.provenance["review"]["status"] == "changes_requested"
        assert run.provenance["review"]["reason"] == "Please correct the quantity"
        assert db.query(TaskRunEvent).filter(
            TaskRunEvent.run_id == run.id,
            TaskRunEvent.event_type == "approval_decided",
        ).count() == 1

        engine.transition(run, "draft")
        second = engine.execute(run, sales)
        assert run.status == "waiting_review"
        assert second.output_refs["form_instance_id"] != str(first_form_id)

        second_approval_id = uuid.UUID(second.output_refs["approval_id"])
        repo.decide_approval(
            tenant_id=tenant.id,
            approval_id=second_approval_id,
            reviewer_id=owner.id,
            reviewer_roles=["owner"],
            expected_version=1,
            idempotency_key="p8-review-approve-001",
            action="approve",
        )
        db.commit()
        db.refresh(run)
        assert run.status == "approved"
        final_form_id = uuid.UUID(second.output_refs["form_instance_id"])
        repo.assert_form_exportable(
            tenant_id=tenant.id,
            instance_id=final_form_id,
            actor_id=sales.id,
            actor_roles=["employee"],
        )


class TestSecondTenantIsolation:
    """劇本二：新租戶預設無模組（opt-in）、覆寫不外洩、run 隔離。"""

    def test_new_tenant_has_no_task_access_by_default(self, db):
        tenant_a = _tenant(db, "A")
        tenant_b = _tenant(db, "B")
        user_a = _user(db, tenant_a, "a@a.com")
        user_b = _user(db, tenant_b, "b@b.com")
        _bind(db, tenant_a, "sales_quote",
              allowed_job_role_keys=["sales"], forms=["quote"])
        _assign(db, tenant_a, user_a, "sales", ["sales_quote"])
        _assign(db, tenant_b, user_b, "sales", ["sales_quote"])
        seed_canonical_task_definitions(db)
        db.commit()

        engine = TaskEngine(db)
        # A 租戶可用
        _, created = engine.start_run(
            user=user_a, task_key="quote", idempotency_key="p8-iso-001",
        )
        assert created is True
        # B 租戶無 binding → 拒絕
        with pytest.raises(TaskAccessDenied):
            engine.start_run(user=user_b, task_key="quote", idempotency_key="p8-iso-002")

    def test_tenant_override_does_not_leak(self, db):
        tenant_a = _tenant(db, "A")
        tenant_b = _tenant(db, "B")
        seed_canonical_task_definitions(db)
        db.commit()
        # A 建立覆寫版本
        base = (
            db.query(TaskDefinition)
            .filter(TaskDefinition.task_key == "quote",
                    TaskDefinition.tenant_id.is_(None))
            .one()
        )
        db.add(TaskDefinition(
            id=uuid.uuid4(), tenant_id=tenant_a.id, task_key="quote",
            name="A 專屬報價", version="1.1", status="enabled",
            handler_key=base.handler_key, module_key=base.module_key,
            applicable_job_role_keys=[], required_capabilities=[],
            input_schema={}, output_bindings=[], risk_level="high",
        ))
        db.commit()

        engine = TaskEngine(db)
        resolved_a = engine.resolve_definition(tenant_a.id, "quote")
        resolved_b = engine.resolve_definition(tenant_b.id, "quote")
        assert resolved_a.name == "A 專屬報價"
        assert resolved_b.name == base.name  # B 仍用全域定義

    def test_runs_isolated_between_tenants(self, db):
        tenant_a = _tenant(db, "A")
        tenant_b = _tenant(db, "B")
        user_a = _user(db, tenant_a, "a@a.com")
        user_b = _user(db, tenant_b, "b@b.com")
        for t, u in ((tenant_a, user_a), (tenant_b, user_b)):
            _bind(db, t, "sales_quote",
                  allowed_job_role_keys=["sales"], forms=["quote"])
            _assign(db, t, u, "sales", ["sales_quote"])
        seed_canonical_task_definitions(db)
        db.commit()

        engine = TaskEngine(db)
        engine.start_run(user=user_a, task_key="quote", idempotency_key="p8-iso-010")
        engine.start_run(user=user_b, task_key="quote", idempotency_key="p8-iso-011")

        runs_a = db.query(TaskRun).filter(TaskRun.tenant_id == tenant_a.id).all()
        runs_b = db.query(TaskRun).filter(TaskRun.tenant_id == tenant_b.id).all()
        assert len(runs_a) == 1 and len(runs_b) == 1
        assert runs_a[0].user_id == user_a.id
        assert runs_b[0].user_id == user_b.id


class TestTaskRoleACLMatrix:
    """劇本三：任務層角色 ACL — 能力與職能雙重把關。"""

    def test_viewer_cannot_start_create_content_task(self, db):
        tenant = _tenant(db, "ACL")
        viewer = _user(db, tenant, "viewer@acl.com", role="viewer")
        _bind(db, tenant, "training_knowhow",
              allowed_job_role_keys=["master"], forms=["interview_record"])
        _assign(db, tenant, viewer, "master", ["training_knowhow"])
        seed_canonical_task_definitions(db)
        db.commit()

        engine = TaskEngine(db)
        # viewer 缺 create_content 能力 → interview 任務拒絕
        with pytest.raises(TaskAccessDenied, match="缺少能力"):
            engine.start_run(user=viewer, task_key="interview",
                             idempotency_key="p8-acl-001")

    def test_wrong_job_role_cannot_use_module(self, db):
        tenant = _tenant(db, "ACL2")
        user = _user(db, tenant, "emp@acl2.com")
        _bind(db, tenant, "sales_quote",
              allowed_job_role_keys=["sales"], forms=["quote"])
        _assign(db, tenant, user, "field", ["incident_handover"])  # 職能不含 sales
        seed_canonical_task_definitions(db)
        db.commit()

        engine = TaskEngine(db)
        with pytest.raises(TaskAccessDenied):
            engine.start_run(user=user, task_key="quote",
                             idempotency_key="p8-acl-002")

    def test_admin_role_can_access_admin_module(self, db):
        tenant = _tenant(db, "ACL3")
        admin = _user(db, tenant, "admin@acl3.com", role="admin")
        _bind(db, tenant, "sales_quote",
              allowed_job_role_keys=["sales"], forms=["quote"])
        _assign(db, tenant, admin, "sales", ["sales_quote"])
        seed_canonical_task_definitions(db)
        db.commit()

        engine = TaskEngine(db)
        _, created = engine.start_run(
            user=admin, task_key="quote", idempotency_key="p8-acl-003",
        )
        assert created is True


class TestReviewFixes:
    """Code review findings 的回歸測試。"""

    def test_idempotency_cross_user_denied(self, db):
        """同租戶不同使用者撞 idempotency key → 拒絕，不回傳他人 run。"""
        tenant = _tenant(db, "X")
        user_a = _user(db, tenant, "a@x.com")
        user_b = _user(db, tenant, "b@x.com")
        _bind(db, tenant, "sales_quote",
              allowed_job_role_keys=["sales"], forms=["quote"])
        _assign(db, tenant, user_a, "sales", ["sales_quote"])
        seed_canonical_task_definitions(db)
        db.commit()
        engine = TaskEngine(db)
        engine.start_run(user=user_a, task_key="quote", idempotency_key="shared-key")
        # user_b 指派到同一個職能（role_key 在租戶內唯一）
        role = db.query(JobRole).filter(
            JobRole.tenant_id == tenant.id, JobRole.role_key == "sales"
        ).one()
        db.add(UserJobRoleAssignment(
            id=uuid.uuid4(), tenant_id=tenant.id, user_id=user_b.id,
            job_role_id=role.id, is_primary=True, active=True,
        ))
        db.commit()
        with pytest.raises(TaskAccessDenied, match="idempotency"):
            engine.start_run(user=user_b, task_key="quote", idempotency_key="shared-key")

    def test_transition_owner_cannot_self_approve(self, db):
        """run 擁有者不可經 transition API 自批 waiting_review → approved。"""
        from fastapi import HTTPException

        from app.api.v1.endpoints.tasks import TaskRunTransition, transition_task_run

        tenant = _tenant(db, "Y")
        user = _user(db, tenant, "u@y.com")
        _bind(db, tenant, "sales_quote",
              allowed_job_role_keys=["sales"], forms=["quote"])
        _assign(db, tenant, user, "sales", ["sales_quote"])
        seed_canonical_task_definitions(db)
        db.commit()

        engine = TaskEngine(db)
        run, _ = engine.start_run(
            user=user, task_key="quote", idempotency_key="p8-fix-001",
            inputs={"values": {
                "customer": "台中精機",
                "part_number": "P-100",
                "quantity": 1,
                "unit_price": 100,
                "valid_until": "2026-12-31",
                "payment_terms": "月結30天",
            }},
        )
        engine.execute(run, user)
        db.commit()
        assert run.status == "waiting_review"

        with pytest.raises(HTTPException) as exc_info:
            transition_task_run(
                run_id=run.id,
                body=TaskRunTransition(to_status="approved"),
                db=db,
                current_user=user,
            )
        assert exc_info.value.status_code == 403

        # 擁有者仍可操作自己的生命週期（rejected → draft）
        engine.transition(run, "rejected")
        db.commit()
        result = transition_task_run(
            run_id=run.id,
            body=TaskRunTransition(to_status="draft"),
            db=db,
            current_user=user,
        )
        assert result["status"] == "draft"

    def test_knowhow_draft_isolation_api(self, db):
        """GET /knowhow 與 GET /knowhow/{id} 不洩漏他人草稿。"""
        from fastapi import HTTPException

        from app.api.v1.endpoints.knowhow import get_knowhow, list_knowhow
        from app.services.mka_persistence import MKARepository

        tenant = _tenant(db, "Z")
        owner = _user(db, tenant, "owner@z.com")
        other = _user(db, tenant, "other@z.com")
        admin = _user(db, tenant, "admin@z.com", role="admin")

        repo = MKARepository(db)
        draft = repo.create_knowhow(
            tenant_id=tenant.id, title="師傅心法", summary="s", steps=["1"],
            data={}, owner_id=owner.id,
        )
        approved = repo.create_knowhow(
            tenant_id=tenant.id, title="已核准卡", summary="s", steps=["1"],
            data={}, owner_id=owner.id,
        )
        approved.status = "approved"
        db.commit()

        # 他人 list：只看到 approved
        rows = list_knowhow(status=None, db=db, current_user=other)
        titles = {r["title"] for r in rows}
        assert "已核准卡" in titles
        assert "師傅心法" not in titles

        # 他人 get 草稿 → 403
        with pytest.raises(HTTPException) as exc_info:
            get_knowhow(knowhow_id=draft.id, db=db, current_user=other)
        assert exc_info.value.status_code == 403

        # 擁有者與 admin 可讀草稿
        assert get_knowhow(knowhow_id=draft.id, db=db, current_user=owner)["title"] == "師傅心法"
        assert get_knowhow(knowhow_id=draft.id, db=db, current_user=admin)["title"] == "師傅心法"
