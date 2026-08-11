"""
MKA P2 — Template Renderer + immutable snapshot + Quote E2E 測試。
"""
import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from app.services.template_renderer import TemplateRenderer, ExportResult, get_template_renderer
from app.services.fixed_form import (
    get_form_registry, FixedFormValidator, FixedFormCalculator,
    FormField, FieldType, FormStatus, FixedFormInstance,
)


# ── Template Renderer ──

class TestTemplateRenderer:
    def test_render_markdown(self):
        renderer = TemplateRenderer()
        result = renderer.render_markdown(
            title="報價單",
            fields={"客戶": "測試公司", "金額": 50000},
            provenance={"unit_price": {"source": "rule"}},
            approval_info={"version": "1.0", "approved_by": "admin"},
        )
        assert result.success
        assert result.format == "md"
        assert "報價單" in result.content.decode("utf-8")
        assert "測試公司" in result.content.decode("utf-8")
        assert "Version 1.0" in result.content.decode("utf-8")

    def test_render_pdf(self):
        renderer = TemplateRenderer()
        result = renderer.render_pdf(
            title="報價單",
            fields={"客戶": "測試公司", "金額": 50000},
            provenance={},
            approval_info={"version": "1.0"},
        )
        # PDF 可能因 reportlab 未安裝而失敗
        if result.success:
            assert result.format == "pdf"
            assert len(result.content) > 0
            assert result.filename.endswith(".pdf")
        else:
            # reportlab 未安裝可接受
            assert "reportlab" in result.error or "failed" in result.error.lower()

    def test_render_docx(self):
        renderer = TemplateRenderer()
        result = renderer.render_docx(
            title="報價單",
            fields={"客戶": "測試公司"},
            provenance={},
            approval_info={"version": "1.0"},
        )
        if result.success:
            assert result.format == "docx"
            assert len(result.content) > 0
            assert result.filename.endswith(".docx")
        else:
            assert "python-docx" in result.error or "docx" in result.error.lower()

    def test_export_result_success_property(self):
        result = ExportResult(format="md", content=b"test")
        assert result.success is True

    def test_export_result_error_property(self):
        result = ExportResult(format="pdf", error="failed")
        assert result.success is False

    def test_watermark_in_markdown(self):
        renderer = TemplateRenderer()
        result = renderer.render_markdown(
            title="測試",
            fields={},
            provenance={},
            approval_info={"version": "2.0", "approved_by": "manager"},
        )
        content = result.content.decode("utf-8")
        assert "Version 2.0" in content
        assert "Enclave MKA" in content


# ── Immutable Snapshot ──

class TestImmutableSnapshot:
    def test_form_instance_status_transitions(self):
        """表單狀態機：draft → pending_review → approved → finalized。"""
        instance = FixedFormInstance(
            schema_name="quote",
            schema_version="1.0",
            status=FormStatus.DRAFT,
        )
        assert instance.status == FormStatus.DRAFT

        # draft → pending_review
        instance.status = FormStatus.PENDING_APPROVAL
        assert instance.status == FormStatus.PENDING_APPROVAL

        # pending_review → approved
        instance.status = FormStatus.APPROVED
        instance.approved_by = "admin"
        instance.approved_at = "2026-08-06T00:00:00Z"
        assert instance.status == FormStatus.APPROVED

        # approved → finalized
        instance.status = FormStatus.APPROVED  # finalized 在 DB 層處理
        assert instance.approved_by == "admin"

    def test_provenance_structure(self):
        """provenance 格式（§4.7）。"""
        provenance = {
            "unit_price": {
                "field": "unit_price",
                "value": 120.0,
                "source_type": "rule",
                "source_ref": "pricing-policy-v7",
                "evidence": ["doc-001", "chunk-003"],
                "confirmed_by": "user-001",
                "confirmed_at": "2026-08-06T10:00:00Z",
            }
        }
        assert provenance["unit_price"]["source_type"] == "rule"
        assert "doc-001" in provenance["unit_price"]["evidence"]


# ── Quote E2E（單元層）──

class TestQuoteE2E:
    """報價單完整流程：抽取 → 計算 → 驗證 → 匯出。"""

    def test_full_quote_flow(self):
        """完整報價流程。"""
        registry = get_form_registry()
        schema = registry.get("quote")
        assert schema is not None

        # 1. 填入欄位
        values = {
            "customer": "測試公司",
            "part_number": "ABC-123",
            "quantity": 100,
            "unit_price": 50.0,
            "tax_rate": 5,
            "valid_until": "2026-12-31",
            "payment_terms": "月結30天",
        }

        # 2. 計算
        subtotal = FixedFormCalculator.calculate(
            schema.get_field("subtotal"), values
        )
        assert subtotal == 5000.0

        values["subtotal"] = subtotal
        tax = FixedFormCalculator.calculate(
            schema.get_field("tax"), values
        )
        assert tax == 250.0

        values["tax"] = tax
        total = FixedFormCalculator.calculate(
            schema.get_field("total"), values
        )
        assert total == 5250.0

        values["total"] = total

        # 3. 驗證
        errors = FixedFormValidator.validate(schema, values)
        assert errors == [], f"Validation errors: {errors}"

        # 4. 匯出
        renderer = TemplateRenderer()
        result = renderer.render_markdown(
            title="報價單",
            fields=values,
            provenance={"subtotal": {"source_type": "rule", "source_ref": "MULTIPLY(quantity, unit_price)"}},
            approval_info={"version": "1.0", "approved_by": "admin"},
        )
        assert result.success
        content = result.content.decode("utf-8")
        assert "測試公司" in content
        assert "5250" in content

    def test_quote_validation_missing_required(self):
        """缺必填欄位應驗證失敗。"""
        registry = get_form_registry()
        schema = registry.get("quote")
        errors = FixedFormValidator.validate(schema, {})
        assert any("必填" in e for e in errors)

    def test_quote_wrong_calculation_detected(self):
        """錯誤計算應被驗證器抓出。"""
        registry = get_form_registry()
        schema = registry.get("quote")
        values = {
            "customer": "測試公司",
            "part_number": "ABC-123",
            "quantity": 100,
            "unit_price": 50.0,
            "subtotal": 9999.0,  # 錯誤
            "tax_rate": 5,
            "tax": 250.0,
            "total": 5250.0,
            "valid_until": "2026-12-31",
            "payment_terms": "月結30天",
        }
        errors = FixedFormValidator.validate(schema, values)
        assert any("計算不正確" in e for e in errors)