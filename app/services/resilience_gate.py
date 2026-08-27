"""Fail-closed P4 resilience, disaster-recovery, and alert evidence gate."""

from __future__ import annotations

from typing import Any

from app.services.rollback_gate import evaluate_rollback_evidence

REQUIRED_FAULT_SCENARIOS = {
    "redis_unavailable",
    "worker_unavailable",
    "asr_provider_unavailable",
    "ocr_provider_unavailable",
    "embedding_provider_unavailable",
    "object_store_unavailable",
    "clamav_unavailable",
    "database_connection_unavailable",
    "network_timeout",
    "duplicate_job_delivery",
}

REQUIRED_LIVE_FAULT_SCENARIOS = {
    "redis_unavailable",
    "worker_unavailable",
    "embedding_provider_unavailable",
    "object_store_unavailable",
    "database_connection_unavailable",
    "network_timeout",
    "duplicate_job_delivery",
}

REQUIRED_ALERTS = {
    "HighErrorRate",
    "HighLatency",
    "ServiceDown",
    "DatabaseUnavailable",
    "HighConcurrency",
}

SAFE_TERMINAL_STATES = {
    "degraded",
    "failed_retryable",
    "review_required",
    "queued",
    "recovered",
    "rejected",
}


def _exact_names(rows: list[dict[str, Any]], key: str) -> set[str]:
    return {str(row.get(key) or "") for row in rows if row.get(key)}


def evaluate_p4_resilience_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Validate operator-produced P4 evidence without inventing missing results."""

    errors: list[str] = []

    rollback = evaluate_rollback_evidence(evidence.get("rollback_evidence") or {})
    if rollback["status"] != "PASS":
        errors.extend(f"rollback: {error}" for error in rollback["errors"])

    restore = evidence.get("restore_drill") or {}
    if (
        restore.get("status") != "PASS"
        or restore.get("isolated_environment") is not True
    ):
        errors.append("fresh isolated restore drill has not passed")
    if restore.get("source_mutated") is not False:
        errors.append("restore drill did not attest source_mutated=false")
    for component in ("database", "object_store", "index", "configuration"):
        row = restore.get(component) or {}
        if row.get("backup_status") != "PASS" or row.get("restore_status") != "PASS":
            errors.append(f"{component} backup/restore has not passed")
        digest = str(row.get("sha256") or "")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            errors.append(f"{component} sha256 is invalid")
    database = restore.get("database") or {}
    if not isinstance(database.get("table_count"), int) or database["table_count"] <= 0:
        errors.append("restored database table inventory is missing")
    objects = restore.get("object_store") or {}
    object_count = objects.get("objects")
    object_bytes = objects.get("bytes")
    if (
        not isinstance(object_count, int)
        or object_count < 0
        or objects.get("restored_objects") != object_count
        or not isinstance(object_bytes, int)
        or object_bytes < 0
        or objects.get("restored_bytes") != object_bytes
    ):
        errors.append("restored object inventory differs from backup")
    index = restore.get("index") or {}
    if not str(index.get("inventory") or "").strip():
        errors.append("restored index inventory is missing")
    configuration = restore.get("configuration") or {}
    if configuration.get("secret_material_included") is not False:
        errors.append(
            "configuration backup contains or did not rule out secret material"
        )
    config_files = configuration.get("files")
    config_bytes = configuration.get("bytes")
    if (
        not isinstance(config_files, int)
        or config_files < 0
        or configuration.get("restored_files") != config_files
        or not isinstance(config_bytes, int)
        or config_bytes < 0
        or configuration.get("restored_bytes") != config_bytes
    ):
        errors.append("restored configuration inventory differs from backup")
    rto = restore.get("rto_seconds")
    rpo = restore.get("rpo_seconds")
    rto_target = restore.get("rto_target_seconds")
    rpo_target = restore.get("rpo_target_seconds")
    if not all(isinstance(value, int) and value >= 0 for value in (rto, rpo)):
        errors.append("measured RTO/RPO is missing")
    if (
        not isinstance(rto_target, int)
        or rto_target <= 0
        or (isinstance(rto, int) and rto > rto_target)
    ):
        errors.append("restore RTO target was not met")
    if (
        not isinstance(rpo_target, int)
        or rpo_target < 0
        or (isinstance(rpo, int) and rpo > rpo_target)
    ):
        errors.append("restore RPO target was not met")

    faults = evidence.get("fault_injection") or []
    fault_names = _exact_names(faults, "scenario")
    missing_faults = sorted(REQUIRED_FAULT_SCENARIOS - fault_names)
    unknown_faults = sorted(fault_names - REQUIRED_FAULT_SCENARIOS)
    if missing_faults:
        errors.append(f"missing fault scenarios: {', '.join(missing_faults)}")
    if unknown_faults:
        errors.append(f"unknown fault scenarios: {', '.join(unknown_faults)}")
    for row in faults:
        name = str(row.get("scenario") or "")
        if row.get("status") != "PASS" or row.get("recovered") is not True:
            errors.append(f"fault scenario did not recover: {name}")
        if (
            name in REQUIRED_LIVE_FAULT_SCENARIOS
            and row.get("execution_class") != "live"
        ):
            errors.append(f"fault scenario requires live execution: {name}")
        if row.get("execution_class") not in {"live", "contract"}:
            errors.append(f"fault scenario execution class is invalid: {name}")
        for invariant in ("data_loss", "cross_tenant_leak", "false_completion"):
            if row.get(invariant) not in (0, "0"):
                errors.append(f"fault scenario violated {invariant}: {name}")
        if row.get("terminal_state") not in SAFE_TERMINAL_STATES:
            errors.append(f"fault scenario terminal state is unsafe: {name}")
        if not row.get("operator_message"):
            errors.append(f"fault scenario has no operator/UI message: {name}")

    alerts = evidence.get("alert_lifecycle") or []
    alert_names = _exact_names(alerts, "alert")
    missing_alerts = sorted(REQUIRED_ALERTS - alert_names)
    unknown_alerts = sorted(alert_names - REQUIRED_ALERTS)
    if missing_alerts:
        errors.append(f"missing alert lifecycle tests: {', '.join(missing_alerts)}")
    if unknown_alerts:
        errors.append(f"unknown alert lifecycle tests: {', '.join(unknown_alerts)}")
    for row in alerts:
        name = str(row.get("alert") or "")
        if row.get("fire_status") != "PASS" or row.get("recover_status") != "PASS":
            errors.append(f"alert fire/recover test failed: {name}")

    runtime = evidence.get("runtime_verification") or {}
    if runtime.get("health_status") != "PASS":
        errors.append("post-drill health verification failed")
    for key in ("data_loss", "cross_tenant_leak", "false_completion"):
        if runtime.get(key) not in (0, "0"):
            errors.append(f"post-drill runtime verification found {key}")

    if not evidence.get("operator") or not evidence.get("completed_at"):
        errors.append("P4 operator attestation is missing")
    return {"status": "PASS" if not errors else "HOLD", "errors": errors}
