from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.capacity_gate import (
    PROFILE_NAMES,
    CapacitySpecError,
    capacity_spec_sha256,
    evaluate_p5_capacity_evidence,
    load_capacity_spec,
    profile_load_target,
    validate_capacity_spec,
)

ROOT = Path(__file__).resolve().parents[1]


def _rows(names: list[str], field: str) -> list[dict]:
    return [{field: name, "status": "PASS"} for name in names]


def _complete_evidence() -> dict:
    spec = load_capacity_spec()
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    environment_capture = now - timedelta(hours=74)
    capacity_start = environment_capture + timedelta(minutes=1)
    capacity_completed = capacity_start + timedelta(minutes=16)
    cost_started = capacity_completed + timedelta(minutes=1)
    cost_completed = cost_started + timedelta(minutes=1)
    degradation_started = cost_completed + timedelta(minutes=1)
    degradation_completed = degradation_started + timedelta(minutes=4)
    soak_start = degradation_completed + timedelta(minutes=1)
    soak_completed = soak_start + timedelta(hours=72)
    environment_hashes = {"lite": "6" * 64, "standard": "7" * 64, "enterprise": "8" * 64}
    environments = [
        {
            "status": "PASS",
            "execution_class": "live",
            "isolated_staging": True,
            "compose_project": f"enclave-p5-{name}",
            "source_commit": "a" * 40,
            "observed_hardware": spec["profiles"][name]["hardware"],
            "runtime_images": {
                "web": {
                    "container": "enclave-p5-web-1",
                    "container_id": "web-container-id",
                    "image_id": "sha256:" + "b" * 64,
                },
                "worker": {
                    "container": "enclave-p5-worker-1",
                    "container_id": "worker-container-id",
                    "image_id": "sha256:" + "b" * 64,
                },
            },
            "co_resident_enclave_projects": [],
            "artifact_sha256": environment_hashes[name],
            "captured_at": environment_capture.isoformat(),
        }
        for name in PROFILE_NAMES
    ]
    reports = []
    for name in PROFILE_NAMES:
        reports.append(
            {
                "profile": name,
                "status": "PASS",
                "execution_class": "live",
                "source_commit": "a" * 40,
                "compose_project": f"enclave-p5-{name}",
                "environment_artifact_sha256": environment_hashes[name],
                "metrics_container_identity": {
                    "container": "enclave-p5-web-1",
                    "container_id": "web-container-id",
                    "compose_project": f"enclave-p5-{name}",
                    "compose_service": "web",
                    "running": True,
                    "image_id": "sha256:" + "b" * 64,
                },
                "backend_container_identity": {
                    "container": "enclave-p5-worker-1",
                    "container_id": "worker-container-id",
                    "compose_project": f"enclave-p5-{name}",
                    "compose_service": "worker",
                    "running": True,
                    "image_id": "sha256:" + "b" * 64,
                },
                "capacity_spec_sha256": capacity_spec_sha256(spec),
                "started_at": capacity_start.isoformat(),
                "completed_at": capacity_completed.isoformat(),
                "duration_seconds": 900,
                "observed_hardware": spec["profiles"][name]["hardware"],
                "achieved_load": profile_load_target(spec, name),
                "scenarios": _rows(spec["required_scenarios"], "scenario"),
                "telemetry": _rows(spec["required_telemetry"], "metric"),
                "telemetry_sample_count": 15,
                "telemetry_interval_seconds": 60,
                "telemetry_integrity": {"status": "PASS", "errors": []},
                "integrity": {
                    "status": "PASS",
                    "data_corruption": 0,
                    "cross_tenant_leak": 0,
                    "unrecoverable_backlog": 0,
                    "execution_class": "live",
                    "artifact_sha256": "d" * 64,
                    "tenant_isolation_status": "PASS",
                    "job_reconciliation_status": "PASS",
                    "source_commit": "a" * 40,
                    "tenant_id": "11111111-1111-1111-1111-111111111111",
                    "run_started_at": capacity_start.isoformat(),
                    "load_completed_at": capacity_completed.isoformat(),
                },
                "grounding_evidence": {
                    "status": "PASS",
                    "execution_class": "live",
                    "publication_class": "isolated_staging_fixture",
                    "kb_revision_id": "22222222-2222-2222-2222-222222222222",
                    "marker": "P5-SOP-RESET-042",
                    "source_commit": "a" * 40,
                    "tenant_id": "11111111-1111-1111-1111-111111111111",
                    "search_results": 5,
                    "chat_sources": 3,
                    "artifact_sha256": "c" * 64,
                },
                "raw_artifacts": {
                    "locust_stats_sha256": "e" * 64,
                    "telemetry_sha256": "f" * 64,
                },
            }
        )
    return {
        "schema_version": 2,
        "gate": "P5-CAPACITY",
        "capacity_spec_sha256": capacity_spec_sha256(spec),
        "environments": environments,
        "capacity_reports": reports,
        "soak_test": {
            "profile": "standard",
            "status": "PASS",
            "execution_class": "live",
            "capacity_spec_sha256": capacity_spec_sha256(spec),
            "source_commit": "a" * 40,
            "compose_project": "enclave-p5-standard",
            "environment_artifact_sha256": environment_hashes["standard"],
            "started_at": soak_start.isoformat(),
            "completed_at": soak_completed.isoformat(),
            "duration_seconds": 72 * 60 * 60,
            "target_duration_seconds": 72 * 60 * 60,
            "observed_hardware": spec["profiles"]["standard"]["hardware"],
            "telemetry_sample_count": 830,
            "telemetry_integrity": {"status": "PASS", "errors": []},
            "metrics_container_identity": {
                "container": "enclave-p5-web-1",
                "container_id": "web-container-id",
                "compose_project": "enclave-p5-standard",
                "compose_service": "web",
                "running": True,
                "image_id": "sha256:" + "b" * 64,
            },
            "memory_growth_percent": 2.0,
            "db_pool_exhaustion_events": 0,
            "ending_unrecoverable_backlog": 0,
            "achieved_load": {
                "concurrent_users": 100,
                "requests_per_minute": 1200,
            },
            "scenarios": _rows(spec["required_scenarios"], "scenario"),
            "grounding_evidence": {
                "status": "PASS",
                "execution_class": "live",
                "publication_class": "isolated_staging_fixture",
                "kb_revision_id": "22222222-2222-2222-2222-222222222222",
                "source_commit": "a" * 40,
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "search_results": 5,
                "chat_sources": 3,
                "artifact_sha256": "9" * 64,
            },
            "raw_artifacts": {
                "locust_stats_sha256": "1" * 64,
                "telemetry_sha256": "2" * 64,
            },
        },
        "cost_guardrails": {
            "status": "PASS",
            "overage_unbounded": False,
            "execution_class": "live",
            "artifact_sha256": "3" * 64,
            "started_at": cost_started.isoformat(),
            "completed_at": cost_completed.isoformat(),
            "source_commit": "a" * 40,
            "compose_project": "enclave-p5-standard",
            "environment_artifact_sha256": environment_hashes["standard"],
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "runtime_container_identity": {
                "container": "enclave-p5-web-1",
                "container_id": "web-container-id",
                "compose_project": "enclave-p5-standard",
                "compose_service": "web",
                "running": True,
                "image_id": "sha256:" + "b" * 64,
            },
            "unit_reports": _rows(list(spec["cost_units"]), "unit"),
        },
        "degradation_tests": [
            {
                **row,
                "execution_class": "live",
                "artifact_sha256": "4" * 64,
                "source_commit": "a" * 40,
                "compose_project": "enclave-p5-standard",
                "environment_artifact_sha256": environment_hashes["standard"],
                "started_at": degradation_started.isoformat(),
                "completed_at": degradation_completed.isoformat(),
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "data_loss": 0,
                "false_completion": 0,
                "cross_tenant_leak": 0,
                "recovered": True,
            }
            for row in _rows(spec["required_degradation_scenarios"], "scenario")
        ],
        "operator": "p5-test",
        "completed_at": now.isoformat(),
    }


def test_checked_in_capacity_spec_is_valid_and_has_three_profiles():
    spec = load_capacity_spec()
    assert tuple(spec["profiles"]) == PROFILE_NAMES
    assert profile_load_target(spec, "standard")["concurrent_users"] == 200


def test_deployment_profiles_consume_the_authoritative_capacity_spec():
    from app.services.deployment import PROFILES, DeploymentProfile

    spec = load_capacity_spec()
    for name in PROFILE_NAMES:
        deployment = PROFILES[DeploymentProfile(name)]
        assert deployment.capacity == spec["profiles"][name]
        assert (
            deployment.hardware.cpu_cores
            == spec["profiles"][name]["hardware"]["cpu_cores"]
        )
        assert (
            deployment.hardware.ram_gb == spec["profiles"][name]["hardware"]["ram_gb"]
        )


def test_invalid_spec_fails_closed():
    spec = load_capacity_spec()
    spec["test_policy"]["soak_min_duration_seconds"] = 3600
    with pytest.raises(CapacitySpecError, match="72 hours"):
        validate_capacity_spec(spec)


def test_invalid_numeric_capacity_contract_fails_closed():
    spec = load_capacity_spec()
    spec["profiles"]["lite"]["hardware"]["cpu_cores"] = "unknown"
    spec["profiles"]["standard"]["slo"]["availability"] = 1.5
    spec["profiles"]["enterprise"]["resource_limits"]["cpu_percent"] = 101
    spec["test_policy"]["capacity_min_samples"] = 0
    spec["test_policy"]["telemetry_sample_interval_seconds"] = 301
    with pytest.raises(CapacitySpecError) as raised:
        validate_capacity_spec(spec)
    message = str(raised.value)
    assert "hardware.cpu_cores must be numeric" in message
    assert "availability cannot exceed 1" in message
    assert "cpu_percent cannot exceed 100" in message
    assert "capacity_min_samples must be at least 15" in message
    assert "telemetry_sample_interval_seconds cannot exceed 300" in message


def test_blank_template_holds():
    template = json.loads(
        (ROOT / "docs" / "templates" / "P5_CAPACITY_EVIDENCE.json").read_text(
            encoding="utf-8"
        )
    )
    result = evaluate_p5_capacity_evidence(template)
    assert result["status"] == "HOLD"
    assert result["errors"]


def test_formal_soak_cannot_use_lite_profile():
    evidence = _complete_evidence()
    evidence["soak_test"]["profile"] = "lite"
    result = evaluate_p5_capacity_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "formal 72-hour soak must use the Standard profile" in result["errors"]


def test_complete_live_evidence_passes():
    assert evaluate_p5_capacity_evidence(_complete_evidence()) == {
        "status": "PASS",
        "errors": [],
    }


def test_short_or_future_soak_cannot_pass():
    evidence = _complete_evidence()
    evidence["soak_test"]["duration_seconds"] = 3600
    evidence["soak_test"]["completed_at"] = (
        datetime.now(timezone.utc) + timedelta(hours=1)
    ).isoformat()
    result = evaluate_p5_capacity_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "soak duration is less than 72 hours" in result["errors"]
    assert "soak completion timestamp is in the future" in result["errors"]


def test_soak_must_sustain_peak_and_all_scenarios():
    evidence = _complete_evidence()
    evidence["soak_test"]["achieved_load"]["requests_per_minute"] = 1199
    evidence["soak_test"]["scenarios"] = evidence["soak_test"]["scenarios"][:-1]
    result = evaluate_p5_capacity_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "soak did not sustain expected request rate" in result["errors"]
    assert any("soak_test.scenarios missing" in error for error in result["errors"])


def test_missing_media_scenario_or_telemetry_holds():
    evidence = _complete_evidence()
    evidence["capacity_reports"][0]["scenarios"] = [
        row
        for row in evidence["capacity_reports"][0]["scenarios"]
        if row["scenario"] != "video_queue"
    ]
    evidence["capacity_reports"][0]["telemetry_sample_count"] = 2
    result = evaluate_p5_capacity_evidence(evidence)
    assert result["status"] == "HOLD"
    assert any("video_queue" in error for error in result["errors"])
    assert "insufficient telemetry samples: lite" in result["errors"]


def test_capacity_telemetry_integrity_failure_holds():
    evidence = _complete_evidence()
    evidence["capacity_reports"][0]["telemetry_integrity"] = {
        "status": "FAIL",
        "errors": ["telemetry source commit mismatch at sample 4"],
    }
    evidence["capacity_reports"][0]["telemetry_interval_seconds"] = 61
    evidence["capacity_reports"][0]["backend_container_identity"][
        "compose_project"
    ] = "enclave-production"
    result = evaluate_p5_capacity_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "capacity telemetry integrity failed: lite" in result["errors"]
    assert "capacity telemetry interval is invalid: lite" in result["errors"]
    assert "capacity backend container identity is incomplete: lite" in result["errors"]


def test_cross_environment_images_and_mixed_tenants_cannot_pass():
    evidence = _complete_evidence()
    evidence["capacity_reports"][0]["metrics_container_identity"]["image_id"] = (
        "sha256:" + "c" * 64
    )
    evidence["soak_test"]["environment_artifact_sha256"] = "f" * 64
    evidence["cost_guardrails"]["tenant_id"] = (
        "99999999-9999-9999-9999-999999999999"
    )
    result = evaluate_p5_capacity_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "capacity metrics runtime image mismatch: lite" in result["errors"]
    assert "soak references an unknown environment artifact" in result["errors"]
    assert "P5 evidence is not bound to one dedicated tenant" in result["errors"]


def test_campaign_rejects_duplicates_stale_capture_and_hardware_drift():
    evidence = _complete_evidence()
    evidence["capacity_reports"].append(dict(evidence["capacity_reports"][0]))
    evidence["capacity_reports"][-1]["observed_hardware"] = {
        **evidence["capacity_reports"][-1]["observed_hardware"],
        "ram_gb": 999,
    }
    evidence["environments"][0]["captured_at"] = evidence["soak_test"]["started_at"]
    result = evaluate_p5_capacity_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "capacity reports must contain each profile exactly once" in result["errors"]
    assert "capacity hardware environment mismatch: lite" in result["errors"]
    assert "capacity started before environment capture: lite" in result["errors"]


def test_cost_or_integrity_failure_holds():
    evidence = _complete_evidence()
    evidence["cost_guardrails"]["overage_unbounded"] = True
    evidence["capacity_reports"][2]["integrity"]["cross_tenant_leak"] = 1
    result = evaluate_p5_capacity_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "cost guardrails did not fail closed" in result["errors"]
    assert any("cross_tenant_leak" in error for error in result["errors"])


def test_ungrounded_http_success_cannot_pass():
    evidence = _complete_evidence()
    evidence["capacity_reports"][0]["grounding_evidence"]["chat_sources"] = 0
    result = evaluate_p5_capacity_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "grounded retrieval proof is incomplete: lite" in result["errors"]


def test_stale_or_cross_release_integrity_evidence_cannot_pass():
    evidence = _complete_evidence()
    evidence["capacity_reports"][0]["integrity"]["source_commit"] = "b" * 40
    evidence["capacity_reports"][1]["integrity"]["run_started_at"] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).isoformat()
    result = evaluate_p5_capacity_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "capacity integrity release mismatch: lite" in result["errors"]
    assert "capacity integrity start-time mismatch: standard" in result["errors"]


def test_environment_cannot_claim_isolation_without_measured_evidence():
    evidence = _complete_evidence()
    evidence["environments"][0]["status"] = "HOLD"
    evidence["environments"][0]["co_resident_enclave_projects"] = ["enclave"]
    result = evaluate_p5_capacity_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "environment[0] must be PASS" in result["errors"]
    assert "environment[0] contains co-resident projects" in result["errors"]
