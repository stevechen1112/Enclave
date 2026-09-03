from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "product_reality_core_journey",
    ROOT / "scripts" / "run_product_reality_core_journey.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_identity_search_is_exact_not_substring():
    identities = {"asset-123", "document-456"}
    assert MODULE._contains_identity({"document_id": "document-456"}, identities)
    assert not MODULE._contains_identity(
        {"text": "prefix-document-456-suffix"}, identities
    )


def test_asset_ready_requires_canonical_terminal_states():
    assert MODULE._asset_ready(
        {
            "status": "ready",
            "revision": {"ingestion_status": "ready"},
            "job": {"status": "ready"},
        }
    )
    assert not MODULE._asset_ready(
        {
            "status": "processing",
            "revision": {"ingestion_status": "ready"},
            "job": {"status": "ready"},
        }
    )


def test_marker_search_handles_nested_payloads():
    assert MODULE._contains_marker(
        {"results": [{"content": "PRA-E2E-0123456789 marker"}]},
        "PRA-E2E-0123456789",
    )
