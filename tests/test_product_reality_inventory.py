from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "product_reality_inventory", ROOT / "scripts" / "product_reality_inventory.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_pra0_inventory_discovers_core_surfaces():
    routes = MODULE.collect_api_routes(ROOT)
    route_pairs = {(item["method"], item["path"]) for item in routes}
    assert ("POST", "/api/v1/auth/login/access-token") in route_pairs
    assert any(path.startswith("/api/v1/knowledge/") for _, path in route_pairs)

    tasks = MODULE.collect_tasks(ROOT)
    assert any(item["function"] == "process_document_task" for item in tasks)
    assert any(item["task"] == "tasks.sync_connector" for item in tasks)

    flags = {item["key"]: item for item in MODULE.collect_feature_flags(ROOT)}
    assert flags["KNOWLEDGE_DECISION_MODE"]["declared_default"] == "off"
    assert (
        flags["KNOWLEDGE_DECISION_AUTHORIZATION_REQUIRED"]["declared_default"] is False
    )


def test_pra0_inventory_separates_pack_surfaces_and_product_validation():
    packs = MODULE.collect_packs(ROOT)
    applications = {
        item["key"]: item for item in packs if item["kind"] == "application_pack"
    }
    assert "sales_quote" in applications
    assert "training_knowhow" in applications
    assert applications["training_knowhow"]["product_validation"] == "UNVERIFIED"
    assert all(item["reality_level"] == "R1" for item in applications.values())


def test_pra0_inventory_discovers_connector_and_provider_contracts():
    connectors = {item["key"] for item in MODULE.collect_connectors(ROOT)}
    assert connectors == {"google_drive", "nas_smb", "sharepoint"}
    providers = {item["role"] for item in MODULE.collect_providers(ROOT)}
    assert {"main_llm", "embedding", "cloud_ocr", "long_audio"} <= providers
