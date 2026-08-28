"""P5 capacity specification and fail-closed evidence evaluation.

This module validates evidence; it never performs or manufactures a load test.
All runners consume the same versioned profile specification used by this gate.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.hardware_inventory import hardware_shortfalls

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC_PATH = ROOT / "config" / "capacity_profiles.json"
PROFILE_NAMES = ("lite", "standard", "enterprise")


class CapacitySpecError(ValueError):
    """The checked-in capacity specification is incomplete or invalid."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def load_capacity_spec(path: Path | None = None) -> dict[str, Any]:
    source = path or DEFAULT_SPEC_PATH
    data = json.loads(source.read_text(encoding="utf-8"))
    validate_capacity_spec(data)
    return data


def capacity_spec_sha256(spec: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(spec)).hexdigest()


def validate_capacity_spec(spec: dict[str, Any]) -> None:
    errors: list[str] = []
    if spec.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    profiles = spec.get("profiles")
    if not isinstance(profiles, dict):
        errors.append("profiles must be an object")
        profiles = {}
    missing_profiles = sorted(set(PROFILE_NAMES) - set(profiles))
    if missing_profiles:
        errors.append(f"missing profiles: {', '.join(missing_profiles)}")
    for name in PROFILE_NAMES:
        profile = profiles.get(name, {})
        for section in ("hardware", "expected_peak", "slo", "resource_limits"):
            if not isinstance(profile.get(section), dict) or not profile[section]:
                errors.append(f"profile {name} missing {section}")
        peak = profile.get("expected_peak", {})
        for field in (
            "concurrent_users",
            "requests_per_minute",
            "ingest_jobs_per_hour",
            "media_hours_per_day",
        ):
            if float(peak.get(field, 0) or 0) <= 0:
                errors.append(f"profile {name} expected_peak.{field} must be positive")
    for field in (
        "required_scenarios",
        "required_telemetry",
        "required_degradation_scenarios",
    ):
        values = spec.get(field)
        if (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(values))
        ):
            errors.append(f"{field} must be a non-empty unique list")
    costs = spec.get("cost_units", {})
    for field in ("storage_gb_month", "audio_hour", "video_hour", "queries_1000"):
        if float(costs.get(field, 0) or 0) <= 0:
            errors.append(f"cost_units.{field} must be positive")
    policy = spec.get("test_policy", {})
    if float(policy.get("peak_multiplier", 0) or 0) < 2:
        errors.append("test_policy.peak_multiplier must be at least 2")
    if int(policy.get("soak_min_duration_seconds", 0) or 0) < 72 * 60 * 60:
        errors.append("test_policy.soak_min_duration_seconds must be at least 72 hours")
    ratio = float(policy.get("soak_min_sample_ratio", 0) or 0)
    if not 0 < ratio <= 1:
        errors.append("test_policy.soak_min_sample_ratio must be in (0, 1]")
    if errors:
        raise CapacitySpecError("; ".join(errors))


def profile_load_target(
    spec: dict[str, Any], profile_name: str
) -> dict[str, int | float]:
    if profile_name not in PROFILE_NAMES:
        raise CapacitySpecError(f"unknown profile: {profile_name}")
    peak = spec["profiles"][profile_name]["expected_peak"]
    factor = float(spec["test_policy"]["peak_multiplier"])
    return {
        field: int(value * factor) if isinstance(value, int) else value * factor
        for field, value in peak.items()
    }


def _parse_timestamp(value: Any, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} is required")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} must be ISO-8601")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field} must include timezone")
        return None
    return parsed.astimezone(timezone.utc)


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _require_complete_rows(
    rows: Any,
    required: set[str],
    *,
    name_field: str,
    section: str,
    errors: list[str],
) -> None:
    if not isinstance(rows, list):
        errors.append(f"{section} must be a list")
        return
    by_name = {
        row.get(name_field): row
        for row in rows
        if isinstance(row, dict) and row.get(name_field)
    }
    missing = sorted(required - set(by_name))
    if missing:
        errors.append(f"{section} missing: {', '.join(missing)}")
    for name in sorted(required & set(by_name)):
        if by_name[name].get("status") != "PASS":
            errors.append(f"{section} did not pass: {name}")


def evaluate_p5_capacity_evidence(
    evidence: dict[str, Any], spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return PASS only when P5 evidence proves every mandatory gate."""

    spec = spec or load_capacity_spec()
    errors: list[str] = []
    if evidence.get("schema_version") != 1:
        errors.append("evidence schema_version must be 1")
    if evidence.get("gate") != "P5-CAPACITY":
        errors.append("evidence gate must be P5-CAPACITY")
    expected_hash = capacity_spec_sha256(spec)
    if evidence.get("capacity_spec_sha256") != expected_hash:
        errors.append("capacity specification hash mismatch")
    if evidence.get("environment", {}).get("isolated_staging") is not True:
        errors.append("tests must run in isolated staging")
    source_commit = str(evidence.get("environment", {}).get("source_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        errors.append("source commit must be a full lowercase Git SHA")
    runtime_images = evidence.get("environment", {}).get("runtime_images")
    if not isinstance(runtime_images, dict) or not runtime_images:
        errors.append("runtime image identities are required")
    elif any(len(str(value or "")) < 12 for value in runtime_images.values()):
        errors.append("runtime image identities are incomplete")

    policy = spec["test_policy"]
    reports = evidence.get("capacity_reports")
    if not isinstance(reports, list):
        errors.append("capacity_reports must be a list")
        reports = []
    by_profile = {
        row.get("profile"): row
        for row in reports
        if isinstance(row, dict) and row.get("profile")
    }
    missing_profiles = sorted(set(PROFILE_NAMES) - set(by_profile))
    if missing_profiles:
        errors.append(f"missing capacity reports: {', '.join(missing_profiles)}")
    for profile_name in PROFILE_NAMES:
        row = by_profile.get(profile_name)
        if row is None:
            continue
        if row.get("status") != "PASS" or row.get("execution_class") != "live":
            errors.append(f"capacity report must be live PASS: {profile_name}")
        if row.get("capacity_spec_sha256") != expected_hash:
            errors.append(f"capacity report specification mismatch: {profile_name}")
        raw_artifacts = row.get("raw_artifacts", {})
        for artifact_name in ("locust_stats_sha256", "telemetry_sha256"):
            value = str(raw_artifacts.get(artifact_name) or "")
            if len(value) != 64:
                errors.append(
                    f"capacity report missing raw artifact hash: {profile_name}.{artifact_name}"
                )
        started = _parse_timestamp(
            row.get("started_at"), f"{profile_name}.started_at", errors
        )
        completed = _parse_timestamp(
            row.get("completed_at"), f"{profile_name}.completed_at", errors
        )
        duration = int(row.get("duration_seconds", 0) or 0)
        if duration < int(policy["capacity_min_duration_seconds"]):
            errors.append(f"capacity duration too short: {profile_name}")
        if started and completed:
            elapsed = (completed - started).total_seconds()
            if elapsed < duration or completed > datetime.now(timezone.utc):
                errors.append(f"capacity timestamps are inconsistent: {profile_name}")
        target = profile_load_target(spec, profile_name)
        hardware_errors = hardware_shortfalls(
            row.get("observed_hardware", {}),
            spec["profiles"][profile_name]["hardware"],
        )
        if hardware_errors:
            errors.append(
                f"capacity host does not qualify for {profile_name}: "
                + "; ".join(hardware_errors)
            )
        achieved = row.get("achieved_load", {})
        for field in ("concurrent_users", "requests_per_minute"):
            if float(achieved.get(field, 0) or 0) < float(target[field]):
                errors.append(f"2x peak not achieved for {profile_name}.{field}")
        _require_complete_rows(
            row.get("scenarios"),
            set(spec["required_scenarios"]),
            name_field="scenario",
            section=f"{profile_name}.scenarios",
            errors=errors,
        )
        _require_complete_rows(
            row.get("telemetry"),
            set(spec["required_telemetry"]),
            name_field="metric",
            section=f"{profile_name}.telemetry",
            errors=errors,
        )
        if int(row.get("telemetry_sample_count", 0) or 0) < int(
            policy["capacity_min_samples"]
        ):
            errors.append(f"insufficient telemetry samples: {profile_name}")
        integrity = row.get("integrity", {})
        if integrity.get("status") != "PASS":
            errors.append(f"capacity integrity evidence did not pass: {profile_name}")
        for field in ("data_corruption", "cross_tenant_leak", "unrecoverable_backlog"):
            if int(integrity.get(field, -1)) != 0:
                errors.append(f"capacity integrity failure for {profile_name}.{field}")
        if integrity.get("execution_class") != "live":
            errors.append(f"capacity integrity evidence is not live: {profile_name}")
        if integrity.get("source_commit") != source_commit:
            errors.append(
                f"capacity integrity release mismatch: {profile_name}"
            )
        if integrity.get("tenant_id") != row.get("grounding_evidence", {}).get(
            "tenant_id"
        ):
            errors.append(
                f"capacity integrity tenant mismatch: {profile_name}"
            )
        if integrity.get("run_started_at") != row.get("started_at"):
            errors.append(
                f"capacity integrity start-time mismatch: {profile_name}"
            )
        if integrity.get("load_completed_at") != row.get("completed_at"):
            errors.append(
                f"capacity integrity completion-time mismatch: {profile_name}"
            )
        if len(str(integrity.get("artifact_sha256") or "")) != 64:
            errors.append(
                f"capacity integrity artifact hash is missing: {profile_name}"
            )
        for field in ("tenant_isolation_status", "job_reconciliation_status"):
            if integrity.get(field) != "PASS":
                errors.append(
                    f"capacity integrity check did not pass: {profile_name}.{field}"
                )
        grounding = row.get("grounding_evidence", {})
        if (
            grounding.get("status") != "PASS"
            or grounding.get("execution_class") != "live"
            or grounding.get("publication_class") != "isolated_staging_fixture"
            or not str(grounding.get("kb_revision_id") or "").strip()
            or not str(grounding.get("marker") or "").strip()
            or grounding.get("source_commit") != source_commit
            or not str(grounding.get("tenant_id") or "").strip()
            or int(grounding.get("search_results", 0) or 0) <= 0
            or int(grounding.get("chat_sources", 0) or 0) <= 0
            or len(str(grounding.get("artifact_sha256") or "")) != 64
        ):
            errors.append(f"grounded retrieval proof is incomplete: {profile_name}")

    soak = evidence.get("soak_test", {})
    if soak.get("status") != "PASS" or soak.get("execution_class") != "live":
        errors.append("72-hour soak must be a live PASS")
    soak_started = _parse_timestamp(
        soak.get("started_at"), "soak_test.started_at", errors
    )
    soak_completed = _parse_timestamp(
        soak.get("completed_at"), "soak_test.completed_at", errors
    )
    soak_duration = int(soak.get("duration_seconds", 0) or 0)
    soak_profile = str(soak.get("profile") or "")
    if soak_profile not in PROFILE_NAMES:
        errors.append("soak profile is invalid")
    required_duration = int(policy["soak_min_duration_seconds"])
    if soak_duration < required_duration:
        errors.append("soak duration is less than 72 hours")
    if soak_started and soak_completed:
        elapsed = (soak_completed - soak_started).total_seconds()
        if elapsed < required_duration or elapsed < soak_duration:
            errors.append("soak timestamps do not prove the reported duration")
        if soak_completed > datetime.now(timezone.utc):
            errors.append("soak completion timestamp is in the future")
    interval = int(policy["telemetry_sample_interval_seconds"])
    min_samples = math.ceil(
        (required_duration / interval) * float(policy["soak_min_sample_ratio"])
    )
    if int(soak.get("telemetry_sample_count", 0) or 0) < min_samples:
        errors.append("soak telemetry sample count is insufficient")
    soak_artifacts = soak.get("raw_artifacts", {})
    for artifact_name in ("locust_stats_sha256", "telemetry_sha256"):
        if len(str(soak_artifacts.get(artifact_name) or "")) != 64:
            errors.append(f"soak raw artifact hash is missing: {artifact_name}")
    if _number(soak.get("memory_growth_percent"), float("inf")) > float(
        policy["max_memory_growth_percent"]
    ):
        errors.append("soak memory growth exceeded limit")
    if _number(soak.get("db_pool_exhaustion_events"), float("inf")) > int(
        policy["max_db_pool_exhaustion_events"]
    ):
        errors.append("soak observed database pool exhaustion")
    if _number(soak.get("ending_unrecoverable_backlog"), float("inf")) > int(
        policy["max_unrecoverable_backlog"]
    ):
        errors.append("soak ended with unrecoverable backlog")
    if soak_profile in PROFILE_NAMES:
        peak = spec["profiles"][soak_profile]["expected_peak"]
        hardware_errors = hardware_shortfalls(
            soak.get("observed_hardware", {}),
            spec["profiles"][soak_profile]["hardware"],
        )
        if hardware_errors:
            errors.append(
                "soak host does not qualify for profile: " + "; ".join(hardware_errors)
            )
        achieved = soak.get("achieved_load", {})
        if int(achieved.get("concurrent_users", 0) or 0) < int(
            peak["concurrent_users"]
        ):
            errors.append("soak did not sustain expected concurrent users")
        if _number(achieved.get("requests_per_minute"), 0) < float(
            peak["requests_per_minute"]
        ):
            errors.append("soak did not sustain expected request rate")
    _require_complete_rows(
        soak.get("scenarios"),
        set(spec["required_scenarios"]),
        name_field="scenario",
        section="soak_test.scenarios",
        errors=errors,
    )
    soak_grounding = soak.get("grounding_evidence", {})
    if (
        soak_grounding.get("status") != "PASS"
        or soak_grounding.get("execution_class") != "live"
        or soak_grounding.get("publication_class") != "isolated_staging_fixture"
        or not str(soak_grounding.get("kb_revision_id") or "").strip()
        or soak_grounding.get("source_commit") != source_commit
        or not str(soak_grounding.get("tenant_id") or "").strip()
        or int(soak_grounding.get("search_results", 0) or 0) <= 0
        or int(soak_grounding.get("chat_sources", 0) or 0) <= 0
        or len(str(soak_grounding.get("artifact_sha256") or "")) != 64
    ):
        errors.append("soak grounded retrieval proof is incomplete")

    cost = evidence.get("cost_guardrails", {})
    if cost.get("status") != "PASS" or cost.get("overage_unbounded") is not False:
        errors.append("cost guardrails did not fail closed")
    if cost.get("execution_class") != "live":
        errors.append("cost guardrails require live execution")
    if len(str(cost.get("artifact_sha256") or "")) != 64:
        errors.append("cost guardrail artifact hash is missing")
    _require_complete_rows(
        cost.get("unit_reports"),
        set(spec["cost_units"]),
        name_field="unit",
        section="cost_guardrails.unit_reports",
        errors=errors,
    )
    _require_complete_rows(
        evidence.get("degradation_tests"),
        set(spec["required_degradation_scenarios"]),
        name_field="scenario",
        section="degradation_tests",
        errors=errors,
    )
    degradation_rows = {
        row.get("scenario"): row
        for row in evidence.get("degradation_tests", [])
        if isinstance(row, dict)
    }
    for scenario in spec["required_degradation_scenarios"]:
        row = degradation_rows.get(scenario, {})
        if row.get("execution_class") != "live":
            errors.append(f"degradation test requires live execution: {scenario}")
        if len(str(row.get("artifact_sha256") or "")) != 64:
            errors.append(f"degradation artifact hash is missing: {scenario}")
        if row.get("data_loss", -1) != 0 or row.get("false_completion", -1) != 0:
            errors.append(f"degradation safety failure: {scenario}")
    if not evidence.get("operator"):
        errors.append("operator is required")
    gate_completed = _parse_timestamp(
        evidence.get("completed_at"), "completed_at", errors
    )
    if gate_completed and gate_completed > datetime.now(timezone.utc):
        errors.append("evidence completion timestamp is in the future")
    return {"status": "PASS" if not errors else "HOLD", "errors": errors}
