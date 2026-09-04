from __future__ import annotations

from app.services.media_certification import build_media_certification_report


def _software():
    return {
        "migration_status": "PASS",
        "backend_tests_status": "PASS",
        "frontend_typecheck_status": "PASS",
        "security_review_status": "PASS",
        "rollback_status": "PASS",
        "certification_runner_status": "PASS",
        "source_commit": "a" * 40,
        "working_tree_clean": True,
        "release_manifest_sha256": "b" * 64,
    }


def _external():
    return {
        "device_runs": [
            {"device": "iphone_safari", "physical_device": True, "status": "PASS"},
            {"device": "android_chrome", "physical_device": True, "status": "PASS"},
            {"device": "desktop_chromium", "physical_device": True, "status": "PASS"},
        ],
        "weak_network_status": "PASS",
        "journey_steps_passed": [
            "upload",
            "process",
            "review",
            "publish",
            "ask",
            "citation",
            "revoke",
        ],
        "tenant_corpus": {"audio_count": 60, "video_count": 60, "sealed_ratio": 0.2},
        "quality_gate_status": "PASS",
        "signatures": {
            "tenant_truth_owner": "tenant",
            "product": "product",
            "engineering": "engineering",
        },
    }


def test_software_can_be_ready_without_claiming_pilot_certification():
    report = build_media_certification_report(
        software_evidence=_software(), external_evidence=None
    )
    assert report["status"] == "SOFTWARE_READY_EXTERNAL_PENDING"
    assert report["external_evidence_ready"] is False


def test_synthetic_or_nonphysical_device_cannot_certify():
    external = _external()
    external["device_runs"][0]["physical_device"] = False
    report = build_media_certification_report(
        software_evidence=_software(), external_evidence=external
    )
    assert report["status"] != "PILOT_CERTIFIED"


def test_dirty_unbound_worktree_cannot_be_software_ready():
    software = _software()
    software["working_tree_clean"] = False
    report = build_media_certification_report(
        software_evidence=software, external_evidence=None
    )
    assert report["status"] == "NOT_READY"
    assert report["software_checks"]["clean_release"] is False


def test_complete_independently_signed_evidence_can_certify():
    report = build_media_certification_report(
        software_evidence=_software(), external_evidence=_external()
    )
    assert report["status"] == "PILOT_CERTIFIED"
