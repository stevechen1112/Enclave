"""Fail-closed AV8 certification report builder.

Software readiness and real tenant/device evidence are deliberately independent.
No synthetic fixture, emulator or developer signature can satisfy the external
evidence half of PILOT_CERTIFIED.
"""

from __future__ import annotations

from typing import Any


REQUIRED_DEVICES = {"iphone_safari", "android_chrome", "desktop_chromium"}
REQUIRED_JOURNEY = {
    "upload",
    "process",
    "review",
    "publish",
    "ask",
    "citation",
    "revoke",
}


def build_media_certification_report(
    *, software_evidence: dict[str, Any], external_evidence: dict[str, Any] | None
) -> dict[str, Any]:
    software_checks = {
        "migration": software_evidence.get("migration_status") == "PASS",
        "backend_tests": software_evidence.get("backend_tests_status") == "PASS",
        "frontend_typecheck": software_evidence.get("frontend_typecheck_status")
        == "PASS",
        "security_review": software_evidence.get("security_review_status") == "PASS",
        "rollback": software_evidence.get("rollback_status") == "PASS",
        "runner": software_evidence.get("certification_runner_status") == "PASS",
        "source_commit": len(str(software_evidence.get("source_commit") or "")) == 40,
        "clean_release": software_evidence.get("working_tree_clean") is True,
        "release_manifest": len(
            str(software_evidence.get("release_manifest_sha256") or "")
        )
        == 64,
    }
    software_ready = all(software_checks.values())

    external = external_evidence or {}
    devices = {
        str(row.get("device")): row
        for row in external.get("device_runs", [])
        if isinstance(row, dict)
    }
    device_checks = {
        name: name in devices
        and devices[name].get("status") == "PASS"
        and devices[name].get("physical_device") is True
        for name in REQUIRED_DEVICES
    }
    journey_steps = set(external.get("journey_steps_passed") or [])
    corpus = external.get("tenant_corpus") or {}
    signatures = external.get("signatures") or {}
    external_checks = {
        "physical_devices": all(device_checks.values()),
        "weak_network": external.get("weak_network_status") == "PASS",
        "complete_journey": REQUIRED_JOURNEY <= journey_steps,
        "audio_corpus": int(corpus.get("audio_count") or 0) >= 60,
        "video_corpus": int(corpus.get("video_count") or 0) >= 60,
        "sealed_holdout": float(corpus.get("sealed_ratio") or 0) >= 0.20,
        "truth_owner": bool(signatures.get("tenant_truth_owner")),
        "product_owner": bool(signatures.get("product")),
        "engineering_owner": bool(signatures.get("engineering")),
        "quality_gate": external.get("quality_gate_status") == "PASS",
    }
    external_ready = all(external_checks.values())
    status = (
        "PILOT_CERTIFIED"
        if software_ready and external_ready
        else "SOFTWARE_READY_EXTERNAL_PENDING"
        if software_ready
        else "NOT_READY"
    )
    return {
        "schema_version": 1,
        "status": status,
        "software_ready": software_ready,
        "external_evidence_ready": external_ready,
        "software_checks": software_checks,
        "external_checks": external_checks,
        "device_checks": device_checks,
        "capability_claim": (
            "pilot_certified"
            if status == "PILOT_CERTIFIED"
            else "internal_software_only"
        ),
    }
