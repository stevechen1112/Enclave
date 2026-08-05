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


# ── P1-4 Module Router ──

class TestModuleRouter:
    def test_default_modules_registered(self):
        router = get_module_router()
        modules = router.list_modules()
        assert "procurement" in modules
        assert "sales" in modules
        assert "warehouse" in modules
        assert "production" in modules
        assert "quality" in modules
        assert "finance" in modules
        assert "hr" in modules

    def test_get_module(self):
        router = get_module_router()
        module = router.get_module("procurement")
        assert module is not None
        assert module.label == "採購管理"
        assert "purchase_order" in module.forms

    def test_get_available_modules_no_authz(self):
        router = get_module_router()
        modules = router.get_available_modules(authz=None)
        assert modules == []

    def test_get_available_modules_with_authz(self):
        router = get_module_router()
        authz = MagicMock()
        authz.roles = ["procurement", "owner"]
        authz.department_id = None
        modules = router.get_available_modules(authz)
        module_names = [m.name for m in modules]
        assert "procurement" in module_names

    def test_get_retrieval_scope(self):
        router = get_module_router()
        authz = MagicMock()
        authz.department_id = None
        scope = router.get_retrieval_scope("procurement", authz)
        assert "category" in scope
        assert "採購" in scope["category"]

    def test_get_forms_for_module(self):
        router = get_module_router()
        forms = router.get_forms_for_module("sales")
        assert "quote" in forms

    def test_get_tools_for_module(self):
        router = get_module_router()
        tools = router.get_tools_for_module("warehouse")
        assert "kb_search" in tools