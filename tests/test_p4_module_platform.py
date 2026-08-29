"""
MKA P4 — 模組平台化測試。
"""
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.module_admin import (
    CompatibilityMatrix, CompatibilityEntry,
    ModuleAdminService, get_compatibility_matrix,
)


class TestCompatibilityMatrix:
    def test_default_entries(self):
        matrix = CompatibilityMatrix()
        entries = matrix.list_entries()
        keys = [e["module_key"] for e in entries]
        assert "sales_quote" in keys
        assert "incident_handover" in keys

    def test_check_compatible(self):
        matrix = CompatibilityMatrix()
        ok, reason = matrix.check_compatibility("sales_quote", "1.0")
        assert ok is True

    def test_check_incompatible_unknown(self):
        matrix = CompatibilityMatrix()
        ok, reason = matrix.check_compatibility("unknown_module", "1.0")
        assert ok is False
        assert "not in compatibility matrix" in reason

    def test_check_required_packs_missing(self):
        matrix = CompatibilityMatrix()
        ok, reason = matrix.check_compatibility(
            "quality_8d", "1.0", enabled_packs=[]
        )
        assert ok is False
        assert "knowledge_compiler" in reason

    def test_check_required_packs_present(self):
        matrix = CompatibilityMatrix()
        ok, reason = matrix.check_compatibility(
            "quality_8d", "1.0", enabled_packs=["knowledge_compiler"]
        )
        assert ok is True

    def test_add_entry(self):
        matrix = CompatibilityMatrix()
        matrix.add_entry(CompatibilityEntry(
            module_key="custom_module",
            module_version="2.0",
            compatible=True,
        ))
        ok, _ = matrix.check_compatibility("custom_module", "2.0")
        assert ok is True


class TestModuleAdminService:
    def test_register_rejects_database_only_application(self):
        svc = ModuleAdminService(MagicMock())

        with pytest.raises(ValueError, match="dedicated Pack manifest"):
            svc.register_module(module_key="new_scenario", name="New scenario")

    def test_enable_with_compatibility_check(self):
        mock_db = MagicMock()
        svc = ModuleAdminService(mock_db)

        # mock module_registry
        with patch("app.services.module_registry.get_module_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_reg.return_value = mock_registry

            result = svc.enable_for_tenant(
                tenant_id=uuid4(),
                module_key="sales_quote",
            )
            assert result["enabled"] is True

    def test_enable_incompatible_module(self):
        mock_db = MagicMock()
        svc = ModuleAdminService(mock_db)

        result = svc.enable_for_tenant(
            tenant_id=uuid4(),
            module_key="quality_8d",
            enabled_packs=[],  # 缺 knowledge_compiler
        )
        assert result["enabled"] is False
        assert "knowledge_compiler" in result["reason"]

    def test_get_compatibility_matrix(self):
        mock_db = MagicMock()
        svc = ModuleAdminService(mock_db)
        matrix = svc.get_compatibility_matrix()
        assert len(matrix) == 4
