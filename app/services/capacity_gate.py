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

from app.services.hardware_inventory import (
    hardware_boundary_errors,
    hardware_shortfalls,
)
from app.services.p5_evidence_binding import runtime_identity_matches_environment

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

    def numeric(
        value: Any, field: str, *, minimum: float = 0, strict: bool = True
    ) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            errors.append(f"{field} must be numeric")
            return float("-inf")
        if (strict and parsed <= minimum) or (not strict and parsed < minimum):
            operator = "greater than" if strict else "at least"
            errors.append(f"{field} must be {operator} {minimum:g}")
        return parsed

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
            numeric(peak.get(field), f"profile {name} expected_peak.{field}")
        hardware = profile.get("hardware", {})
        for field in ("cpu_cores", "ram_gb", "disk_gb"):
            numeric(hardware.get(field), f"profile {name} hardware.{field}")
        numeric(
            hardware.get("gpu_vram_gb"),
            f"profile {name} hardware.gpu_vram_gb",
            strict=False,
        )
        slo = profile.get("slo", {})
        availability = numeric(
            slo.get("availability"), f"profile {name} slo.availability"
        )
        error_rate = numeric(
            slo.get("api_error_rate"),
            f"profile {name} slo.api_error_rate",
            strict=False,
        )
        if availability > 1:
            errors.append(f"profile {name} slo.availability cannot exceed 1")
        if error_rate >= 1:
            errors.append(f"profile {name} slo.api_error_rate must be less than 1")
        for field in (
            "search_p95_ms",
            "chat_p95_ms",
            "upload_p95_ms",
            "ingest_lag_p95_seconds",
        ):
            numeric(slo.get(field), f"profile {name} slo.{field}")
        limits = profile.get("resource_limits", {})
        for field in (
            "cpu_percent",
            "memory_percent",
            "db_pool_percent",
            "redis_memory_percent",
        ):
            value = numeric(limits.get(field), f"profile {name} resource_limits.{field}")
            if value > 100:
                errors.append(
                    f"profile {name} resource_limits.{field} cannot exceed 100"
                )
        numeric(limits.get("queue_depth"), f"profile {name} resource_limits.queue_depth")
        provider_error_rate = numeric(
            limits.get("provider_error_rate"),
            f"profile {name} resource_limits.provider_error_rate",
            strict=False,
        )
        if provider_error_rate >= 1:
            errors.append(
                f"profile {name} resource_limits.provider_error_rate must be less than 1"
            )
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
        numeric(costs.get(field), f"cost_units.{field}")
    policy = spec.get("test_policy", {})
    if numeric(policy.get("peak_multiplier"), "test_policy.peak_multiplier") < 2:
        errors.append("test_policy.peak_multiplier must be at least 2")
    if numeric(
        policy.get("capacity_min_duration_seconds"),
        "test_policy.capacity_min_duration_seconds",
    ) < 900:
        errors.append("test_policy.capacity_min_duration_seconds must be at least 900")
    if numeric(
        policy.get("capacity_min_samples"), "test_policy.capacity_min_samples"
    ) < 15:
        errors.append("test_policy.capacity_min_samples must be at least 15")
    if numeric(
        policy.get("soak_min_duration_seconds"),
        "test_policy.soak_min_duration_seconds",
    ) < 72 * 60 * 60:
        errors.append("test_policy.soak_min_duration_seconds must be at least 72 hours")
    interval = numeric(
        policy.get("telemetry_sample_interval_seconds"),
        "test_policy.telemetry_sample_interval_seconds",
    )
    if interval > 300:
        errors.append(
            "test_policy.telemetry_sample_interval_seconds cannot exceed 300"
        )
    ratio = numeric(
        policy.get("soak_min_sample_ratio"), "test_policy.soak_min_sample_ratio"
    )
    if not 0 < ratio <= 1:
        errors.append("test_policy.soak_min_sample_ratio must be in (0, 1]")
    numeric(
        policy.get("max_memory_growth_percent"),
        "test_policy.max_memory_growth_percent",
        strict=False,
    )
    for field in ("max_db_pool_exhaustion_events", "max_unrecoverable_backlog"):
        numeric(policy.get(field), f"test_policy.{field}", strict=False)
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
    if evidence.get("schema_version") != 2:
        errors.append("evidence schema_version must be 2")
    if evidence.get("gate") != "P5-CAPACITY":
        errors.append("evidence gate must be P5-CAPACITY")
    expected_hash = capacity_spec_sha256(spec)
    if evidence.get("capacity_spec_sha256") != expected_hash:
        errors.append("capacity specification hash mismatch")
    environments = evidence.get("environments")
    if not isinstance(environments, list) or not environments:
        errors.append("environments must be a non-empty list")
        environments = []
    environment_by_hash: dict[str, dict[str, Any]] = {}
    source_commits: set[str] = set()
    for index, environment in enumerate(environments):
        if not isinstance(environment, dict):
            errors.append(f"environment[{index}] must be an object")
            continue
        artifact_hash = str(environment.get("artifact_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", artifact_hash):
            errors.append(f"environment[{index}] artifact hash is invalid")
        elif artifact_hash in environment_by_hash:
            errors.append("environment artifact hashes must be unique")
        else:
            environment_by_hash[artifact_hash] = environment
        if environment.get("status") != "PASS":
            errors.append(f"environment[{index}] must be PASS")
        if environment.get("execution_class") != "live":
            errors.append(f"environment[{index}] must be live")
        if environment.get("isolated_staging") is not True:
            errors.append(f"environment[{index}] must be isolated staging")
        if environment.get("co_resident_enclave_projects") != []:
            errors.append(f"environment[{index}] contains co-resident projects")
        commit = str(environment.get("source_commit") or "")
        if re.fullmatch(r"[0-9a-f]{40}", commit):
            source_commits.add(commit)
        else:
            errors.append(f"environment[{index}] source commit is invalid")
        captured = _parse_timestamp(
            environment.get("captured_at"), f"environment[{index}].captured_at", errors
        )
        if captured and captured > datetime.now(timezone.utc):
            errors.append(f"environment[{index}] capture timestamp is in the future")
        hardware = environment.get("observed_hardware", {})
        if not isinstance(hardware, dict) or any(
            field not in hardware
            for field in ("cpu_cores", "ram_gb", "disk_gb", "gpu_vram_gb")
        ):
            errors.append(f"environment[{index}] hardware inventory is incomplete")
        runtime_images = environment.get("runtime_images")
        if not isinstance(runtime_images, dict) or not runtime_images or any(
            not isinstance(value, dict)
            or not str(value.get("container") or "").strip()
            or not str(value.get("container_id") or "").strip()
            or len(str(value.get("image_id") or "")) < 12
            for value in (runtime_images or {}).values()
        ):
            errors.append(f"environment[{index}] runtime images are incomplete")
    source_commit = next(iter(source_commits), "")
    if len(source_commits) != 1:
        errors.append("all P5 environments must use one source commit")

    def bound_environment(artifact_hash: Any, section: str) -> dict[str, Any]:
        environment = environment_by_hash.get(str(artifact_hash or ""))
        if environment is None:
            errors.append(f"{section} references an unknown environment artifact")
            return {}
        return environment
    campaign_tenants: set[str] = set()
    campaign_completions: list[datetime] = []

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
    if len(reports) != len(PROFILE_NAMES) or len(by_profile) != len(reports):
        errors.append("capacity reports must contain each profile exactly once")
    for profile_name in PROFILE_NAMES:
        row = by_profile.get(profile_name)
        if row is None:
            continue
        report_environment = bound_environment(
            row.get("environment_artifact_sha256"), f"capacity.{profile_name}"
        )
        environment_captured = _parse_timestamp(
            report_environment.get("captured_at"),
            f"capacity.{profile_name}.environment.captured_at",
            errors,
        ) if report_environment else None
        environment_hardware = report_environment.get("observed_hardware", {})
        if row.get("status") != "PASS" or row.get("execution_class") != "live":
            errors.append(f"capacity report must be live PASS: {profile_name}")
        if row.get("capacity_spec_sha256") != expected_hash:
            errors.append(f"capacity report specification mismatch: {profile_name}")
        if row.get("source_commit") != source_commit:
            errors.append(f"capacity report source commit mismatch: {profile_name}")
        if row.get("compose_project") != report_environment.get("compose_project"):
            errors.append(f"capacity report Compose project mismatch: {profile_name}")
        metrics_identity = row.get("metrics_container_identity", {})
        if (
            metrics_identity.get("compose_project")
            != report_environment.get("compose_project")
            or metrics_identity.get("running") is not True
            or not str(metrics_identity.get("container_id") or "").strip()
            or not str(metrics_identity.get("compose_service") or "").strip()
            or not str(metrics_identity.get("image_id") or "").strip()
        ):
            errors.append(
                f"capacity metrics container identity is incomplete: {profile_name}"
            )
        elif not runtime_identity_matches_environment(
            report_environment, metrics_identity
        ):
            errors.append(
                f"capacity metrics runtime image mismatch: {profile_name}"
            )
        backend_identity = row.get("backend_container_identity", {})
        if (
            backend_identity.get("compose_project")
            != report_environment.get("compose_project")
            or backend_identity.get("running") is not True
            or not str(backend_identity.get("container_id") or "").strip()
            or not str(backend_identity.get("compose_service") or "").strip()
            or not str(backend_identity.get("image_id") or "").strip()
        ):
            errors.append(
                f"capacity backend container identity is incomplete: {profile_name}"
            )
        elif not runtime_identity_matches_environment(
            report_environment, backend_identity
        ):
            errors.append(
                f"capacity backend runtime image mismatch: {profile_name}"
            )
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
            if environment_captured and started < environment_captured:
                errors.append(
                    f"capacity started before environment capture: {profile_name}"
                )
            campaign_completions.append(completed)
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
        boundary_errors = hardware_boundary_errors(
            row.get("observed_hardware", {}),
            spec["profiles"][profile_name]["hardware"],
        )
        if boundary_errors:
            errors.append(
                f"capacity host is outside {profile_name} boundary: "
                + "; ".join(boundary_errors)
            )
        if row.get("observed_hardware") != environment_hardware:
            errors.append(f"capacity hardware environment mismatch: {profile_name}")
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
        maximum_interval = int(policy["capacity_min_duration_seconds"]) // int(
            policy["capacity_min_samples"]
        )
        if not 0 < int(row.get("telemetry_interval_seconds", 0) or 0) <= maximum_interval:
            errors.append(f"capacity telemetry interval is invalid: {profile_name}")
        if row.get("telemetry_integrity", {}).get("status") != "PASS":
            errors.append(f"capacity telemetry integrity failed: {profile_name}")
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
        grounding_tenant = str(grounding.get("tenant_id") or "").strip()
        if grounding_tenant:
            campaign_tenants.add(grounding_tenant)
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
    soak_environment = bound_environment(
        soak.get("environment_artifact_sha256"), "soak"
    )
    soak_environment_captured = _parse_timestamp(
        soak_environment.get("captured_at"),
        "soak.environment.captured_at",
        errors,
    ) if soak_environment else None
    soak_environment_hardware = soak_environment.get("observed_hardware", {})
    if soak.get("status") != "PASS" or soak.get("execution_class") != "live":
        errors.append("72-hour soak must be a live PASS")
    if soak.get("capacity_spec_sha256") != expected_hash:
        errors.append("soak capacity specification mismatch")
    if soak.get("source_commit") != source_commit:
        errors.append("soak source commit mismatch")
    if soak.get("compose_project") != soak_environment.get("compose_project"):
        errors.append("soak Compose project mismatch")
    if soak.get("telemetry_integrity", {}).get("status") != "PASS":
        errors.append("soak telemetry integrity did not pass")
    metrics_identity = soak.get("metrics_container_identity", {})
    if (
        metrics_identity.get("compose_project")
        != soak_environment.get("compose_project")
        or metrics_identity.get("running") is not True
        or not str(metrics_identity.get("container_id") or "").strip()
        or not str(metrics_identity.get("compose_service") or "").strip()
        or not str(metrics_identity.get("image_id") or "").strip()
    ):
        errors.append("soak metrics container identity is incomplete")
    elif not runtime_identity_matches_environment(soak_environment, metrics_identity):
        errors.append("soak metrics runtime image mismatch")
    soak_started = _parse_timestamp(
        soak.get("started_at"), "soak_test.started_at", errors
    )
    soak_completed = _parse_timestamp(
        soak.get("completed_at"), "soak_test.completed_at", errors
    )
    soak_duration = int(soak.get("duration_seconds", 0) or 0)
    soak_target_duration = int(soak.get("target_duration_seconds", 0) or 0)
    soak_profile = str(soak.get("profile") or "")
    if soak_profile not in PROFILE_NAMES:
        errors.append("soak profile is invalid")
    elif soak_profile != "standard":
        errors.append("formal 72-hour soak must use the Standard profile")
    required_duration = int(policy["soak_min_duration_seconds"])
    if soak_duration < required_duration:
        errors.append("soak duration is less than 72 hours")
    if soak_target_duration < required_duration:
        errors.append("soak target duration is less than 72 hours")
    if soak_started and soak_completed:
        elapsed = (soak_completed - soak_started).total_seconds()
        if elapsed < required_duration or elapsed < soak_duration:
            errors.append("soak timestamps do not prove the reported duration")
        if soak_completed > datetime.now(timezone.utc):
            errors.append("soak completion timestamp is in the future")
        if soak_environment_captured and soak_started < soak_environment_captured:
            errors.append("soak started before environment capture")
        campaign_completions.append(soak_completed)
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
        if soak.get("observed_hardware") != soak_environment_hardware:
            errors.append("soak hardware environment mismatch")
        boundary_errors = hardware_boundary_errors(
            soak.get("observed_hardware", {}),
            spec["profiles"][soak_profile]["hardware"],
        )
        if boundary_errors:
            errors.append(
                "soak host is outside Standard boundary: "
                + "; ".join(boundary_errors)
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
    soak_tenant = str(soak_grounding.get("tenant_id") or "").strip()
    if soak_tenant:
        campaign_tenants.add(soak_tenant)
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
    cost_environment = bound_environment(
        cost.get("environment_artifact_sha256"), "cost_guardrails"
    )
    cost_environment_captured = _parse_timestamp(
        cost_environment.get("captured_at"),
        "cost_guardrails.environment.captured_at",
        errors,
    ) if cost_environment else None
    if cost.get("status") != "PASS" or cost.get("overage_unbounded") is not False:
        errors.append("cost guardrails did not fail closed")
    if cost.get("execution_class") != "live":
        errors.append("cost guardrails require live execution")
    if cost.get("source_commit") != source_commit:
        errors.append("cost guardrail source commit mismatch")
    if cost.get("compose_project") != cost_environment.get("compose_project"):
        errors.append("cost guardrail Compose project mismatch")
    cost_identity = cost.get("runtime_container_identity", {})
    if (
        cost_identity.get("compose_project")
        != cost_environment.get("compose_project")
        or cost_identity.get("running") is not True
        or not str(cost_identity.get("container_id") or "").strip()
        or not str(cost_identity.get("compose_service") or "").strip()
    ):
        errors.append("cost guardrail runtime identity is incomplete")
    elif not runtime_identity_matches_environment(cost_environment, cost_identity):
        errors.append("cost guardrail runtime image mismatch")
    cost_tenant = str(cost.get("tenant_id") or "").strip()
    if cost_tenant:
        campaign_tenants.add(cost_tenant)
    if len(str(cost.get("artifact_sha256") or "")) != 64:
        errors.append("cost guardrail artifact hash is missing")
    cost_started = _parse_timestamp(
        cost.get("started_at"), "cost_guardrails.started_at", errors
    )
    cost_completed = _parse_timestamp(
        cost.get("completed_at"), "cost_guardrails.completed_at", errors
    )
    if cost_started and cost_completed:
        if cost_completed < cost_started or cost_completed > datetime.now(timezone.utc):
            errors.append("cost guardrail timestamps are inconsistent")
        if cost_environment_captured and cost_started < cost_environment_captured:
            errors.append("cost guardrail started before environment capture")
        campaign_completions.append(cost_completed)
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
    degradation_list = evidence.get("degradation_tests", [])
    if (
        not isinstance(degradation_list, list)
        or len(degradation_list) != len(spec["required_degradation_scenarios"])
        or len(degradation_rows) != len(degradation_list)
    ):
        errors.append("degradation tests must contain each scenario exactly once")
    for scenario in spec["required_degradation_scenarios"]:
        row = degradation_rows.get(scenario, {})
        degradation_environment = bound_environment(
            row.get("environment_artifact_sha256"), f"degradation.{scenario}"
        )
        degradation_environment_captured = _parse_timestamp(
            degradation_environment.get("captured_at"),
            f"degradation.{scenario}.environment.captured_at",
            errors,
        ) if degradation_environment else None
        if row.get("status") != "PASS":
            errors.append(f"degradation test did not pass: {scenario}")
        if row.get("execution_class") != "live":
            errors.append(f"degradation test requires live execution: {scenario}")
        if len(str(row.get("artifact_sha256") or "")) != 64:
            errors.append(f"degradation artifact hash is missing: {scenario}")
        if row.get("source_commit") != source_commit:
            errors.append(f"degradation source commit mismatch: {scenario}")
        if row.get("compose_project") != degradation_environment.get(
            "compose_project"
        ):
            errors.append(f"degradation compose project mismatch: {scenario}")
        if not str(row.get("tenant_id") or "").strip():
            errors.append(f"degradation tenant binding is missing: {scenario}")
        else:
            campaign_tenants.add(str(row["tenant_id"]).strip())
        degradation_started = _parse_timestamp(
            row.get("started_at"), f"{scenario}.started_at", errors
        )
        degradation_completed = _parse_timestamp(
            row.get("completed_at"), f"{scenario}.completed_at", errors
        )
        if degradation_started and degradation_completed:
            if (
                degradation_completed < degradation_started
                or degradation_completed > datetime.now(timezone.utc)
            ):
                errors.append(f"degradation timestamps are inconsistent: {scenario}")
            if (
                degradation_environment_captured
                and degradation_started < degradation_environment_captured
            ):
                errors.append(
                    f"degradation started before environment capture: {scenario}"
                )
            campaign_completions.append(degradation_completed)
        if (
            row.get("data_loss", -1) != 0
            or row.get("false_completion", -1) != 0
            or row.get("cross_tenant_leak", -1) != 0
            or row.get("recovered") is not True
        ):
            errors.append(f"degradation safety failure: {scenario}")
    if len(campaign_tenants) != 1:
        errors.append("P5 evidence is not bound to one dedicated tenant")
    if not evidence.get("operator"):
        errors.append("operator is required")
    gate_completed = _parse_timestamp(
        evidence.get("completed_at"), "completed_at", errors
    )
    if gate_completed and gate_completed > datetime.now(timezone.utc):
        errors.append("evidence completion timestamp is in the future")
    if gate_completed and campaign_completions and gate_completed < max(
        campaign_completions
    ):
        errors.append("evidence completion timestamp predates campaign artifacts")
    return {"status": "PASS" if not errors else "HOLD", "errors": errors}
