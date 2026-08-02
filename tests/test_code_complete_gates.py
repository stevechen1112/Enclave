"""Code-complete gates: no fake convergence, packs omit, schemas, chaos helpers."""
from __future__ import annotations

import os
import uuid

import pytest


class TestNoFakeProjectionStubs:
    def test_projection_omits_disabled_packs(self, monkeypatch):
        monkeypatch.setenv("RAGFLOW_ENABLED", "false")
        monkeypatch.setenv("PIPESHUB_ENABLED", "false")
        monkeypatch.setenv("WEKNORA_ENABLED", "false")
        from app.gateway.adapter_factory import build_projection_adapters, build_gateway_adapters

        assert list(build_projection_adapters().keys()) == ["enclave"]
        assert list(build_gateway_adapters().keys()) == ["document"]

    @pytest.mark.asyncio
    async def test_legacy_stubs_never_converge(self):
        from app.gateway.adapters.ragflow import RAGFlowAdapter
        from app.gateway.adapters.pipeshub import PipesHubAdapter
        from app.gateway.adapters.weknora import WeKnoraAdapter

        for adapter in (RAGFlowAdapter(), PipesHubAdapter(), WeKnoraAdapter()):
            r = await adapter.reconcile("document", "x", 1)
            assert r["converged"] is False


class TestConnectorSchemas:
    def test_nas_and_sharepoint_validation(self):
        from app.services.connector_schemas import validate_connector_config, oauth_authorize_url

        nas = validate_connector_config("nas_smb", {"root_path": "C:/docs"})
        assert nas["root_path"] == "C:/docs"
        with pytest.raises(ValueError):
            validate_connector_config("sharepoint", {})
        sp = validate_connector_config(
            "sharepoint",
            {"site_url": "https://contoso.sharepoint.com/sites/a", "client_id": "abc"},
        )
        url = oauth_authorize_url("sharepoint", sp, "state1", "http://localhost/cb")
        assert url and "login.microsoftonline.com" in url and "client_id=abc" in url


class TestOpsAndDocsPresent:
    def test_scripts_and_templates_exist(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for rel in [
            "scripts/chaos_sidecar_down.py",
            "scripts/e2e_module_disable.py",
            "scripts/validate_citation_lineage_online.py",
            "scripts/n1_upgrade.py",
            "scripts/eval_wiki_graph_quality.py",
            "LICENSE",
            "docs/slo/CUSTOMER_SLO_TEMPLATE.md",
            "docs/ops/CAPACITY_ESTIMATOR.md",
        ]:
            assert (root / rel).is_file(), rel
