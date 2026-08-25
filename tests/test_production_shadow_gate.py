from scripts.run_production_shadow import _case_passes, _runtime_manifest_binding_errors


def test_shadow_case_enforces_expected_and_forbidden_documents():
    passed, reasons = _case_passes(
        {"doc-allowed", "doc-forbidden"},
        {
            "min_results": 1,
            "expected_document_ids": ["doc-allowed"],
            "forbidden_document_ids": ["doc-forbidden"],
        },
    )
    assert passed is False
    assert reasons == ["forbidden_document_returned"]


def test_shadow_case_supports_explicit_deny_expectation():
    assert _case_passes(set(), {"expect_no_results": True}) == (True, [])
    passed, reasons = _case_passes({"leaked"}, {"expect_no_results": True})
    assert passed is False
    assert "expected_no_results" in reasons


def test_shadow_runtime_manifest_binds_backend_frontend_and_deployment():
    backend = "sha256:" + "a" * 64
    payload = {
        "image_digest": backend,
        "frontend_image_digest": "sha256:" + "b" * 64,
        "deployment_manifest_id": "dm-" + "c" * 24,
    }
    assert _runtime_manifest_binding_errors(payload, backend) == []
    del payload["frontend_image_digest"]
    assert _runtime_manifest_binding_errors(payload, backend) == ["frontend_image_missing"]
