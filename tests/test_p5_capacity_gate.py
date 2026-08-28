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
    capacity_start = now - timedelta(minutes=16)
    soak_start = now - timedelta(hours=73)
    reports = []
    for name in PROFILE_NAMES:
        reports.append(
            {
                "profile": name,
                "status": "PASS",
                "execution_class": "live",
                "capacity_spec_sha256": capacity_spec_sha256(spec),
                "started_at": capacity_start.isoformat(),
                "completed_at": now.isoformat(),
                "duration_seconds": 900,
                "observed_hardware": spec["profiles"][name]["hardware"],
                "achieved_load": profile_load_target(spec, name),
                "scenarios": _rows(spec["required_scenarios"], "scenario"),
                "telemetry": _rows(spec["required_telemetry"], "metric"),
                "telemetry_sample_count": 15,
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
                    "load_completed_at": now.isoformat(),
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
        "schema_version": 1,
        "gate": "P5-CAPACITY",
        "capacity_spec_sha256": capacity_spec_sha256(spec),
        "environment": {
            "isolated_staging": True,
            "source_commit": "a" * 40,
            "runtime_images": {"backend": "sha256:" + "b" * 64},
        },
        "capacity_reports": reports,
        "soak_test": {
            "profile": "standard",
            "status": "PASS",
            "execution_class": "live",
            "started_at": soak_start.isoformat(),
            "completed_at": now.isoformat(),
            "duration_seconds": 72 * 60 * 60,
            "observed_hardware": spec["profiles"]["standard"]["hardware"],
            "telemetry_sample_count": 830,
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
            "unit_reports": _rows(list(spec["cost_units"]), "unit"),
        },
        "degradation_tests": [
            {
                **row,
                "execution_class": "live",
                "artifact_sha256": "4" * 64,
                "data_loss": 0,
                "false_completion": 0,
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


def test_blank_template_holds():
    template = json.loads(
        (ROOT / "docs" / "templates" / "P5_CAPACITY_EVIDENCE.json").read_text(
            encoding="utf-8"
        )
    )
    result = evaluate_p5_capacity_evidence(template)
    assert result["status"] == "HOLD"
    assert result["errors"]


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
