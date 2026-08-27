from scripts.verify_release_parity import REQUIRED_ROUTES, validate_parity


def _payloads():
    identity = {
        "release_id": "release-42",
        "source_commit": "abc123",
        "source_dirty": "false",
        "schema_head": "phase-p0",
        "route_contract_hash": "hash-1",
    }
    return (
        {"status": "ok", "release": {**identity, "identifiable": True}},
        {**identity, "canonical_routes": sorted(REQUIRED_ROUTES)},
    )


def test_release_parity_accepts_one_identifiable_release():
    health, frontend = _payloads()
    assert validate_parity(health, frontend) == []


def test_release_parity_rejects_mixed_frontend_and_backend():
    health, frontend = _payloads()
    frontend["source_commit"] = "different"
    assert any(
        "source_commit mismatch" in error for error in validate_parity(health, frontend)
    )


def test_release_parity_rejects_missing_canonical_route():
    health, frontend = _payloads()
    frontend["canonical_routes"].remove("/knowledge/assets")
    assert any(
        "/knowledge/assets" in error for error in validate_parity(health, frontend)
    )


def test_release_parity_rejects_dirty_source_build():
    health, frontend = _payloads()
    health["release"]["source_dirty"] = "true"
    frontend["source_dirty"] = "true"
    assert "backend release was built from a dirty source tree" in validate_parity(
        health, frontend
    )
