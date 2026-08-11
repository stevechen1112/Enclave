"""
P1：製造業產品工作層 — 單元測試。

涵蓋：
- P1-1 Voice Interaction Gateway
- P1-2 Fixed Form Schema
- P1-3 Approval State Machine
- P1-4 Module Router
"""
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.voice_gateway import (
    VoiceInteractionGateway,
    TranscriptionResult,
)
from app.services.fixed_form import (
    FixedFormSchema,
    FormField,
    FieldType,
    FormStatus,
    FixedFormValidator,
    FixedFormCalculator,
    get_form_registry,
)
from app.services.approval_state import (
    ApprovalState,
    ApprovalStateMachine,
    ApprovalTransition,
)
from app.services.module_router import ModuleRouter, get_module_router


# ── P1-1 Voice Gateway ──

class TestVoiceGateway:
    def test_transcription_result_draft_default(self):
        result = TranscriptionResult(text="測試")
        assert result.is_draft is True  # 預設 draft

    def test_promote_to_confirmed(self):
        result = TranscriptionResult(text="測試")
        result.promote_to_confirmed()
        assert result.is_draft is False

    def test_extract_confirm_fields_amount(self):
        gateway = VoiceInteractionGateway()
        fields = gateway.extract_confirm_fields(
            "金額是 15000 元，料號 ABC-123",
            ["amount", "part_number"],
        )
        assert len(fields) == 2
        assert fields[0]["type"] == "amount"
        assert "15000" in fields[0]["value"]
        assert fields[1]["type"] == "part_number"
        assert "ABC-123" in fields[1]["value"]
        assert all(f["needs_confirm"] for f in fields)

    def test_extract_confirm_fields_quantity(self):
        gateway = VoiceInteractionGateway()
        fields = gateway.extract_confirm_fields(
            "數量 500 個",
            ["quantity"],
        )
        assert len(fields) == 1
        assert "500" in fields[0]["value"]

    def test_extract_demo_sentence_full_coverage(self):
        """DEMO 例句：幫台中精機報價，料號 P-100，兩百個，單價一百二 → 四欄位全抓。"""
        gateway = VoiceInteractionGateway()
        fields = gateway.extract_confirm_fields(
            "幫台中精機報價，料號 P-100，兩百個，單價一百二",
            ["amount", "unit_price", "part_number", "quantity", "customer"],
        )
        by_type = {f["type"]: f["value"] for f in fields}
        assert by_type["customer"] == "台中精機"
        assert by_type["part_number"] == "P-100"
        assert by_type["quantity"] == "200"
        assert by_type["unit_price"] == "120"

    def test_extract_chinese_numeral_variants(self):
        gateway = VoiceInteractionGateway()
        fields = gateway.extract_confirm_fields(
            "單價三千五，數量二十件",
            ["unit_price", "quantity"],
        )
        by_type = {f["type"]: f["value"] for f in fields}
        assert by_type["unit_price"] == "3500"
        assert by_type["quantity"] == "20"

    def test_extract_customer_verb_frame(self):
        gateway = VoiceInteractionGateway()
        fields = gateway.extract_confirm_fields(
            "給大立光電開單",
            ["customer"],
        )
        assert len(fields) == 1
        assert fields[0]["value"] == "大立光電"

    def test_extract_amount_not_confused_with_unit_price(self):
        """總價與單價是不同型別，可同時抽取。"""
        gateway = VoiceInteractionGateway()
        fields = gateway.extract_confirm_fields(
            "總價 24000 元，單價 120 元",
            ["amount", "unit_price"],
        )
        by_type = {f["type"]: f["value"] for f in fields}
        assert by_type["amount"] == "24000"
        assert by_type["unit_price"] == "120"

    def test_transcribe_requires_authz(self):
        gateway = VoiceInteractionGateway()
        with pytest.raises(ValueError, match="AuthorizationContext"):
            gateway.transcribe(b"audio", authz=None)

    def test_synthesize_requires_authz(self):
        gateway = VoiceInteractionGateway()
        with pytest.raises(ValueError, match="AuthorizationContext"):
            gateway.synthesize("text", authz=None)


# ── P1-2 Fixed Form ──

class TestFixedForm:
    def test_quote_form_registered(self):
        registry = get_form_registry()
        schema = registry.get("quote")
        assert schema is not None
        assert schema.name == "quote"
        assert schema.require_approval is True

    def test_required_fields(self):
        registry = get_form_registry()
        schema = registry.get("quote")
        required = schema.get_required_fields()
        required_names = [f.name for f in required]
        assert "customer" in required_names
        assert "part_number" in required_names
        assert "quantity" in required_names

    def test_validate_missing_required(self):
        registry = get_form_registry()
        schema = registry.get("quote")
        errors = FixedFormValidator.validate(schema, {})
        assert any("必填" in e for e in errors)

    def test_validate_correct_values(self):
        registry = get_form_registry()
        schema = registry.get("quote")
        values = {
            "customer": "測試公司",
            "part_number": "ABC-123",
            "quantity": 100,
            "unit_price": 50.0,
            "subtotal": 5000.0,
            "tax_rate": 5,
            "tax": 250.0,
            "total": 5250.0,
            "valid_until": "2026-12-31",
            "payment_terms": "月結30天",
        }
        errors = FixedFormValidator.validate(schema, values)
        assert errors == []

    def test_calculate_subtotal(self):
        field = FormField(name="subtotal", label="小計", type=FieldType.AMOUNT,
                          calculated=True, formula="MULTIPLY(quantity, unit_price)")
        values = {"quantity": 100, "unit_price": 50.0}
        result = FixedFormCalculator.calculate(field, values)
        assert result == 5000.0

    def test_calculate_tax(self):
        field = FormField(name="tax", label="稅額", type=FieldType.AMOUNT,
                          calculated=True, formula="TAX(subtotal, 5)")
        values = {"subtotal": 5000.0}
        result = FixedFormCalculator.calculate(field, values)
        assert result == 250.0

    def test_calculate_total(self):
        field = FormField(name="total", label="總計", type=FieldType.AMOUNT,
                          calculated=True, formula="TOTAL(subtotal, tax)")
        values = {"subtotal": 5000.0, "tax": 250.0}
        result = FixedFormCalculator.calculate(field, values)
        assert result == 5250.0

    def test_validate_wrong_calculation(self):
        registry = get_form_registry()
        schema = registry.get("quote")
        values = {
            "customer": "測試公司",
            "part_number": "ABC-123",
            "quantity": 100,
            "unit_price": 50.0,
            "subtotal": 9999.0,  # 錯誤：應為 5000
            "tax_rate": 5,
            "tax": 250.0,
            "total": 5250.0,
            "valid_until": "2026-12-31",
            "payment_terms": "月結30天",
        }
        errors = FixedFormValidator.validate(schema, values)
        assert any("計算不正確" in e for e in errors)

    def test_validate_invalid_select(self):
        registry = get_form_registry()
        schema = registry.get("quote")
        values = {
            "customer": "測試公司",
            "part_number": "ABC-123",
            "quantity": 100,
            "unit_price": 50.0,
            "subtotal": 5000.0,
            "tax_rate": 5,
            "tax": 250.0,
            "total": 5250.0,
            "valid_until": "2026-12-31",
            "payment_terms": "不合法的選項",
        }
        errors = FixedFormValidator.validate(schema, values)
        assert any("選項不合法" in e for e in errors)

    def test_purchase_order_form(self):
        registry = get_form_registry()
        schema = registry.get("purchase_order")
        assert schema is not None
        assert "supplier" in [f.name for f in schema.fields]


# ── P1-3 Approval State Machine ──

class TestApprovalStateMachine:
    def test_create_request(self):
        sm = ApprovalStateMachine(timeout_hours=24)
        ctx = sm.create_request(
            tool_name="create_purchase_order",
            tool_risk="high_risk_write",
            actor_id=uuid4(),
            actor_name="test_user",
            action_summary="建立採購單",
        )
        assert ctx.state == ApprovalState.PENDING
        assert ctx.request_id is not None

    def test_approve_idempotent(self):
        sm = ApprovalStateMachine(timeout_hours=24)
        ctx = sm.create_request(
            tool_name="test_tool",
            tool_risk="high_risk_write",
            actor_id=uuid4(),
            actor_name="test_user",
            action_summary="測試",
        )
        # 第一次核准
        ctx1 = sm.approve(ctx.request_id, approved_by="admin")
        assert ctx1.state == ApprovalState.APPROVED
        # 第二次核准（冪等）
        ctx2 = sm.approve(ctx.request_id, approved_by="admin")
        assert ctx2.state == ApprovalState.APPROVED

    def test_reject_idempotent(self):
        sm = ApprovalStateMachine(timeout_hours=24)
        ctx = sm.create_request(
            tool_name="test_tool",
            tool_risk="high_risk_write",
            actor_id=uuid4(),
            actor_name="test_user",
            action_summary="測試",
        )
        ctx1 = sm.reject(ctx.request_id, rejected_by="admin", reason="不合理")
        assert ctx1.state == ApprovalState.REJECTED
        ctx2 = sm.reject(ctx.request_id, rejected_by="admin", reason="不合理")
        assert ctx2.state == ApprovalState.REJECTED

    def test_cannot_approve_rejected(self):
        sm = ApprovalStateMachine(timeout_hours=24)
        ctx = sm.create_request(
            tool_name="test_tool",
            tool_risk="high_risk_write",
            actor_id=uuid4(),
            actor_name="test_user",
            action_summary="測試",
        )
        sm.reject(ctx.request_id, rejected_by="admin")
        with pytest.raises(ValueError, match="Cannot approve"):
            sm.approve(ctx.request_id, approved_by="admin")

    def test_confirm_fields_required(self):
        sm = ApprovalStateMachine(timeout_hours=24)
        ctx = sm.create_request(
            tool_name="create_purchase_order",
            tool_risk="high_risk_write",
            actor_id=uuid4(),
            actor_name="test_user",
            action_summary="建立採購單",
            confirm_fields=[{"type": "amount", "value": "50000", "needs_confirm": True}],
        )
        assert ctx.needs_confirmation is True
        # 不提供 confirmed_fields 應報錯
        with pytest.raises(ValueError, match="requires field confirmation"):
            sm.approve(ctx.request_id, approved_by="admin")
        # 提供後應成功
        ctx2 = sm.approve(ctx.request_id, approved_by="admin", confirmed_fields={"amount": "50000"})
        assert ctx2.state == ApprovalState.APPROVED

    def test_expired_check(self):
        import time
        sm = ApprovalStateMachine(timeout_hours=0)  # 0 小時 = 立即過期
        ctx = sm.create_request(
            tool_name="test_tool",
            tool_risk="high_risk_write",
            actor_id=uuid4(),
            actor_name="test_user",
            action_summary="測試",
        )
        # 等一小段時間讓它過期
        time.sleep(0.1)
        expired = sm.check_expired()
        assert len(expired) == 1
        assert expired[0].state == ApprovalState.EXPIRED

    def test_transition_rules(self):
        assert ApprovalTransition.can_transition(ApprovalState.PENDING, ApprovalState.APPROVED)
        assert ApprovalTransition.can_transition(ApprovalState.PENDING, ApprovalState.REJECTED)
        assert not ApprovalTransition.can_transition(ApprovalState.REJECTED, ApprovalState.APPROVED)
        assert not ApprovalTransition.can_transition(ApprovalState.EXECUTED, ApprovalState.PENDING)


# ── P1-4 Module Router（DB-backed 契約）──

class TestModuleRouter:
    @pytest.fixture()
    def db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        import app.models  # noqa: F401 - register relationship targets
        from app.db.base_class import Base
        from app.models.mka import JobModule, TenantModuleBinding

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            engine, tables=[JobModule.__table__, TenantModuleBinding.__table__]
        )
        session = sessionmaker(bind=engine)()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()

    def test_canonical_modules_seeded_from_db(self, db):
        router = get_module_router(db=db)
        modules = router.list_modules()
        for key in (
            "spec_sop",
            "sales_quote",
            "incident_handover",
            "quality_8d",
            "training_knowhow",
        ):
            assert key in modules

    def test_get_module(self, db):
        router = get_module_router(db=db)
        module = router.get_module("sales_quote")
        assert module is not None
        assert module.label == "業務報價"
        assert "quote" in module.forms

    def test_get_available_modules_no_authz(self, db):
        router = get_module_router(db=db)
        modules = router.get_available_modules(authz=None)
        assert modules == []

    def _bind_all(self, db, tenant_id):
        """新租戶 opt-in：測試用，為指定租戶啟用全部 canonical 模組。"""
        from app.models.mka import JobModule, TenantModuleBinding

        for m in db.query(JobModule).filter(JobModule.tenant_id.is_(None)).all():
            db.add(TenantModuleBinding(
                tenant_id=tenant_id, module_key=m.module_key,
                enabled=True, license_state="active", config_json={},
            ))
        db.flush()

    def test_get_available_modules_with_authz(self, db):
        router = get_module_router(db=db)
        authz = MagicMock()
        authz.tenant_id = uuid4()
        authz.roles = ["employee"]
        authz.department_id = None
        self._bind_all(db, authz.tenant_id)
        modules = router.get_available_modules(authz)
        module_names = [m.name for m in modules]
        assert "sales_quote" in module_names
        assert "spec_sop" in module_names

    def test_get_available_modules_no_binding_means_opt_in(self, db):
        """新租戶無 binding → 看不到任何全域模組（opt-in 語意）。"""
        router = get_module_router(db=db)
        authz = MagicMock()
        authz.tenant_id = uuid4()
        authz.roles = ["employee"]
        authz.department_id = None
        assert router.get_available_modules(authz) == []

    def test_get_available_modules_role_filtered(self, db):
        router = get_module_router(db=db)
        authz = MagicMock()
        authz.tenant_id = uuid4()
        authz.roles = ["no_such_role"]
        authz.department_id = None
        assert router.get_available_modules(authz) == []

    # ── 真實 AuthorizationContext 契約（role_ids／department_ids）──
    # 回歸防護：router 曾只讀 stub 屬性 roles/department_id，
    # 導致 chat runtime 傳入真實 AuthorizationContext 時模組 ACL 全部誤判為無權。

    def _real_authz(self, roles, departments=None):
        from app.core.authorization import AuthorizationContext

        return AuthorizationContext(
            tenant_id=uuid4(),
            subject_id=uuid4(),
            role_ids=list(roles),
            department_ids=list(departments or []),
        )

    def test_real_authorization_context_employee_gets_modules(self, db):
        router = get_module_router(db=db)
        authz = self._real_authz(["employee"])
        self._bind_all(db, authz.tenant_id)
        names = [m.name for m in router.get_available_modules(authz)]
        assert "sales_quote" in names
        assert "spec_sop" in names

    def test_real_authorization_context_viewer_gets_no_modules(self, db):
        router = get_module_router(db=db)
        authz = self._real_authz(["viewer"])
        assert router.get_available_modules(authz) == []

    def test_real_authorization_context_workspace_entries(self, db):
        router = get_module_router(db=db)
        authz = self._real_authz(["employee"])
        self._bind_all(db, authz.tenant_id)
        entries = router.workspace_entries(authz)
        paths = {e["path"] for e in entries}
        assert "/job/tasks/quote" in paths

    def test_real_authorization_context_department_acl(self, db):
        from app.models.mka import JobModule, TenantModuleBinding

        dept_id = uuid4()
        row = JobModule(
            tenant_id=None,
            module_key="dept_only",
            name="部門限定",
            status="enabled",
            allowed_roles=["employee"],
            allowed_departments=[str(dept_id)],
        )
        db.add(row)
        db.flush()

        router = get_module_router(db=db)
        outsider = self._real_authz(["employee"], departments=[uuid4()])
        self._bind_all(db, outsider.tenant_id)
        names = [m.name for m in router.get_available_modules(outsider)]
        assert "dept_only" not in names

        insider = self._real_authz(["employee"], departments=[dept_id])
        db.add(TenantModuleBinding(
            tenant_id=insider.tenant_id, module_key="dept_only",
            enabled=True, license_state="active", config_json={},
        ))
        db.flush()
        names = [m.name for m in router.get_available_modules(insider)]
        assert "dept_only" in names

    def test_get_retrieval_scope(self, db):
        router = get_module_router(db=db)
        authz = MagicMock()
        authz.department_id = None
        scope = router.get_retrieval_scope("spec_sop", authz)
        assert scope.get("doc_type") == ["sop", "spec"]

    def test_get_forms_for_module(self, db):
        router = get_module_router(db=db)
        forms = router.get_forms_for_module("sales_quote")
        assert "quote" in forms

    def test_get_tools_for_module(self, db):
        router = get_module_router(db=db)
        tools = router.get_tools_for_module("sales_quote")
        assert "price_lookup" in tools