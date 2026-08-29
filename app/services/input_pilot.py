"""Fail-closed Input I8 pilot lifecycle and acceptance evaluation."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.input_pilot import (
    InputPilot,
    InputPilotAcceptance,
    InputPilotAudit,
    InputPilotDailyMetric,
    InputPilotIncident,
)

ALLOWED_JOURNEYS = {
    "nas_batch",
    "document_batch",
    "long_audio",
    "machine_video",
}
REQUIRED_AUDITS = {"quality", "security", "permission"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_ACCEPTANCE = {
    "minimum_days": 14,
    "maximum_days": 28,
    "minimum_success_rate": 0.95,
    "maximum_retry_rate": 0.10,
    "maximum_manual_correction_rate": 0.15,
    "maximum_processing_p95_ms": 3_600_000,
    "minimum_citation_rate": 0.90,
}


def validate_pilot_configuration(pilot: InputPilot) -> list[str]:
    errors: list[str] = []
    journeys = list(pilot.journeys or [])
    if not 2 <= len(journeys) <= 3:
        errors.append("pilot must configure 2 to 3 journeys")
    keys = [str(item.get("key") or "") for item in journeys]
    if len(keys) != len(set(keys)):
        errors.append("pilot journey keys must be unique")
    unknown = sorted(set(keys) - ALLOWED_JOURNEYS)
    if unknown:
        errors.append(f"unsupported pilot journeys: {', '.join(unknown)}")
    for item in journeys:
        key = str(item.get("key") or "missing")
        if not item.get("review_owner_id"):
            errors.append(f"journey {key} missing review owner")
        if not isinstance(item.get("metadata_template"), dict) or not item.get("metadata_template"):
            errors.append(f"journey {key} missing metadata template")
        if not item.get("glossary_ref"):
            errors.append(f"journey {key} missing glossary reference")
        if not item.get("role_acl_ref"):
            errors.append(f"journey {key} missing role/ACL reference")
    if not pilot.dedicated_environment:
        errors.append("dedicated pilot environment is not attested")
    if not _SHA256.fullmatch(str(pilot.environment_evidence_sha256 or "")):
        errors.append("dedicated environment evidence hash is missing or invalid")
    if not str(pilot.data_processing_agreement_ref or "").strip():
        errors.append("data processing agreement reference is required")
    config = {**DEFAULT_ACCEPTANCE, **dict(pilot.acceptance_config or {})}
    try:
        if not 14 <= int(config["minimum_days"]) <= 28:
            errors.append("minimum_days must be between 14 and 28")
        if not int(config["minimum_days"]) <= int(config["maximum_days"]) <= 28:
            errors.append("maximum_days must be between minimum_days and 28")
        for key in (
            "minimum_success_rate",
            "maximum_retry_rate",
            "maximum_manual_correction_rate",
            "minimum_citation_rate",
        ):
            if not 0 <= float(config[key]) <= 1:
                errors.append(f"{key} must be between 0 and 1")
        if int(config["maximum_processing_p95_ms"]) <= 0:
            errors.append("maximum_processing_p95_ms must be positive")
    except (KeyError, TypeError, ValueError):
        errors.append("acceptance configuration is invalid")
    return errors


def evaluate_pilot_gate(
    db: Session,
    *,
    tenant_id: UUID,
    pilot_id: UUID,
    require_acceptance: bool = True,
) -> dict[str, Any]:
    pilot = db.query(InputPilot).filter(
        InputPilot.tenant_id == tenant_id,
        InputPilot.id == pilot_id,
    ).first()
    if pilot is None:
        raise LookupError("pilot not found")
    errors = validate_pilot_configuration(pilot)
    if pilot.evidence_mode != "live":
        errors.append("pilot evidence mode is not live")
    if pilot.started_at is None:
        errors.append("pilot has not started")
    if (
        not _SHA256.fullmatch(str(pilot.retrospective_sha256 or ""))
        or not str(pilot.retrospective_ref or "").strip()
    ):
        errors.append("pilot retrospective evidence is missing")

    metrics = db.query(InputPilotDailyMetric).filter(
        InputPilotDailyMetric.tenant_id == tenant_id,
        InputPilotDailyMetric.pilot_id == pilot_id,
    ).all()
    configured_keys = {str(item["key"]) for item in (pilot.journeys or []) if item.get("key")}
    observed_days = sorted({row.metric_date for row in metrics})
    config = {**DEFAULT_ACCEPTANCE, **dict(pilot.acceptance_config or {})}
    if len(observed_days) < int(config["minimum_days"]):
        errors.append("pilot observation window is shorter than minimum days")
    if len(observed_days) > int(config["maximum_days"]):
        errors.append("pilot observation window exceeds maximum days")
    if observed_days and (observed_days[-1] - observed_days[0]).days + 1 != len(observed_days):
        errors.append("pilot daily observation window is not continuous")
    today = datetime.now(timezone.utc).date()
    if any(day > today for day in observed_days):
        errors.append("pilot metrics contain future dates")
    if pilot.started_at is not None:
        started_date = pilot.started_at.date()
        if any(day < started_date for day in observed_days):
            errors.append("pilot metrics predate pilot start")
        if observed_days and observed_days[0] != started_date:
            errors.append("pilot daily observation does not begin on start date")
        if observed_days and (
            observed_days[-1] - started_date
        ).days + 1 > int(config["maximum_days"]):
            errors.append("pilot evidence extends beyond the configured window")
    observed_keys = {row.journey_key for row in metrics}
    unexpected_journeys = sorted(observed_keys - configured_keys)
    if unexpected_journeys:
        errors.append(
            f"daily metrics contain unconfigured journeys: {', '.join(unexpected_journeys)}"
        )
    missing_journeys = sorted(configured_keys - observed_keys)
    if missing_journeys:
        errors.append(f"journeys missing daily metrics: {', '.join(missing_journeys)}")

    aggregates: dict[str, dict[str, float | int | None]] = {}
    grouped: dict[str, list[InputPilotDailyMetric]] = defaultdict(list)
    for row in metrics:
        grouped[row.journey_key].append(row)
        if not _SHA256.fullmatch(str(row.source_evidence_sha256 or "")):
            errors.append(f"daily metric evidence hash invalid: {row.id}")
    for key in sorted(configured_keys):
        rows = grouped[key]
        attempts = sum(row.total_attempts for row in rows)
        successes = sum(row.successful_attempts for row in rows)
        retries = sum(row.retry_count for row in rows)
        corrections = sum(row.manual_correction_count for row in rows)
        retrievals = sum(row.retrieval_checks for row in rows)
        citations = sum(row.cited_retrievals for row in rows)
        processing_p95 = max((row.processing_p95_ms for row in rows), default=None)
        success_rate = successes / attempts if attempts else 0.0
        retry_rate = retries / attempts if attempts else 0.0
        correction_rate = corrections / attempts if attempts else 0.0
        citation_rate = citations / retrievals if retrievals else 0.0
        aggregates[key] = {
            "days": len({row.metric_date for row in rows}),
            "attempts": attempts,
            "success_rate": round(success_rate, 6),
            "retry_rate": round(retry_rate, 6),
            "manual_correction_rate": round(correction_rate, 6),
            "processing_p95_ms": processing_p95,
            "citation_rate": round(citation_rate, 6),
            "friction_count": sum(row.friction_count for row in rows),
        }
        if attempts == 0:
            errors.append(f"journey {key} has no attempts")
        if aggregates[key]["days"] != len(observed_days):
            errors.append(f"journey {key} does not cover every observed day")
        if success_rate < float(config["minimum_success_rate"]):
            errors.append(f"journey {key} success rate below target")
        if retry_rate > float(config["maximum_retry_rate"]):
            errors.append(f"journey {key} retry rate above target")
        if correction_rate > float(config["maximum_manual_correction_rate"]):
            errors.append(f"journey {key} manual correction rate above target")
        if processing_p95 is None or processing_p95 > int(config["maximum_processing_p95_ms"]):
            errors.append(f"journey {key} processing p95 above target")
        if citation_rate < float(config["minimum_citation_rate"]):
            errors.append(f"journey {key} citation rate below target")

    incidents = db.query(InputPilotIncident).filter(
        InputPilotIncident.tenant_id == tenant_id,
        InputPilotIncident.pilot_id == pilot_id,
    ).all()
    for incident in incidents:
        occurred_at = incident.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        if occurred_at > datetime.now(timezone.utc):
            errors.append(f"incident timestamp is in the future: {incident.id}")
        if pilot.started_at is not None:
            started_at = pilot.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            if occurred_at < started_at:
                errors.append(f"incident predates pilot start: {incident.id}")
        if incident.status != "resolved":
            errors.append(f"unresolved incident: {incident.id}")
        if incident.status == "resolved" and (
            not incident.root_cause
            or not incident.corrective_action
            or not _SHA256.fullmatch(str(incident.retrospective_sha256 or ""))
        ):
            errors.append(f"incident retrospective incomplete: {incident.id}")

    audits = db.query(InputPilotAudit).filter(
        InputPilotAudit.tenant_id == tenant_id,
        InputPilotAudit.pilot_id == pilot_id,
    ).all()
    latest_audits: dict[str, InputPilotAudit] = {}
    for row in audits:
        previous = latest_audits.get(row.audit_type)
        if previous is None or row.audited_at > previous.audited_at:
            latest_audits[row.audit_type] = row
        if not _SHA256.fullmatch(str(row.evidence_sha256 or "")):
            errors.append(f"audit evidence hash invalid: {row.id}")
        audited_at = row.audited_at
        if audited_at.tzinfo is None:
            audited_at = audited_at.replace(tzinfo=timezone.utc)
        if audited_at > datetime.now(timezone.utc):
            errors.append(f"audit timestamp is in the future: {row.id}")
        if pilot.started_at is not None:
            started_at = pilot.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            if audited_at < started_at:
                errors.append(f"audit predates pilot start: {row.id}")
        if row.status == "pass" and row.sample_size <= 0:
            errors.append(f"passing audit has no sample: {row.id}")
    passed_audits = {
        audit_type
        for audit_type, row in latest_audits.items()
        if row.status == "pass"
    }
    missing_audits = sorted(REQUIRED_AUDITS - passed_audits)
    if missing_audits:
        errors.append(f"missing passing audits: {', '.join(missing_audits)}")

    acceptance = db.query(InputPilotAcceptance).filter(
        InputPilotAcceptance.tenant_id == tenant_id,
        InputPilotAcceptance.pilot_id == pilot_id,
    ).first()
    if require_acceptance and (
        acceptance is None
        or acceptance.decision != "accepted"
        or not _SHA256.fullmatch(str(acceptance.signed_document_sha256 or ""))
        or not str(acceptance.signed_document_ref or "").strip()
    ):
        errors.append("signed customer acceptance is missing")
    if acceptance is not None:
        signed_at = acceptance.signed_at
        if signed_at.tzinfo is None:
            signed_at = signed_at.replace(tzinfo=timezone.utc)
        if signed_at > datetime.now(timezone.utc):
            errors.append("customer acceptance timestamp is in the future")
        if pilot.started_at is not None:
            started_at = pilot.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            if signed_at < started_at:
                errors.append("customer acceptance predates pilot start")
        if observed_days and signed_at.date() < observed_days[-1]:
            errors.append("customer acceptance predates the final evidence day")

    return {
        "status": "PASS" if not errors else "HOLD",
        "pilot_id": str(pilot.id),
        "tenant_id": str(tenant_id),
        "observation_days": len(observed_days),
        "journeys": aggregates,
        "incident_count": len(incidents),
        "passed_audits": sorted(passed_audits),
        "signed_acceptance": acceptance is not None,
        "errors": errors,
    }
