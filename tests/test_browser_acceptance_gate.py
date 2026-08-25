from scripts.eval_browser_acceptance_gate import (
    AUTHZ_PAIRS,
    _covered_pairs,
    _passed_names,
    _release_binding_checks,
)


def test_passed_case_requires_traceable_evidence_reference():
    rows = [
        {"name": "login", "status": "PASS"},
        {"name": "quote", "status": "PASS", "evidence_refs": ["trace:quote-1"]},
    ]
    assert _passed_names(rows) == {"quote"}


def test_pairwise_coverage_requires_every_authorization_dimension_pair():
    rows = []
    for left, right in AUTHZ_PAIRS:
        rows.append({
            "status": "PASS",
            "dimensions": {left: "value-a", right: "value-b"},
            "evidence_refs": [f"trace:{left}-{right}"],
        })
    assert _covered_pairs(rows) == AUTHZ_PAIRS

    rows[0]["evidence_refs"] = []
    assert _covered_pairs(rows) != AUTHZ_PAIRS


def test_browser_acceptance_binds_backend_frontend_and_deployment_manifest():
    backend = "sha256:" + "a" * 64
    frontend = "sha256:" + "b" * 64
    manifest = "dm-" + "c" * 24
    values = _release_binding_checks({
        "image_digest": backend,
        "frontend_image_digest": frontend,
        "deployment_manifest_id": manifest,
    })
    assert values[:3] == (backend, frontend, manifest)
    assert all(check["status"] == "PASS" for check in values[3])

    missing_frontend = _release_binding_checks({
        "image_digest": backend,
        "deployment_manifest_id": manifest,
    })
    assert {check["name"] for check in missing_frontend[3] if check["status"] == "FAIL"} == {"frontend_image"}
