"""Cross-tenant evidence and cryptographic attestation for legacy retirement."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.tenant import Tenant
from app.platform.deprecations import SURFACES, get_deprecation_surface
from app.services.rls import apply_rls_bypass


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def build_signed_removal_report(
    db: Session,
    *,
    signing_key: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build an all-active-tenant report; HOLD reports are signed without claiming PASS."""
    if len(signing_key) < 32:
        raise ValueError(
            "removal report signing key must contain at least 32 characters"
        )
    now = now or datetime.now(UTC)
    apply_rls_bypass(
        db,
        actor_identity="legacy-retirement-service",
        operation="build_signed_removal_report",
        reason="Aggregate deprecation evidence across active tenants",
    )
    tenant_ids = [
        str(row[0])
        for row in db.query(Tenant.id).filter(Tenant.status == "active").all()
    ]
    events = (
        db.query(AuditLog.tenant_id, AuditLog.target_id, AuditLog.created_at)
        .filter(AuditLog.action == "legacy_surface_used")
        .all()
    )
    by_tenant_surface: dict[tuple[str, str], list[datetime]] = {}
    for tenant_id, surface_key, created_at in events:
        timestamp = _aware(created_at)
        if timestamp is not None:
            by_tenant_surface.setdefault((str(tenant_id), str(surface_key)), []).append(
                timestamp
            )

    cutoff = now - timedelta(days=30)
    tenants: list[dict[str, Any]] = []
    for tenant_id in sorted(tenant_ids):
        evidence = []
        for surface in SURFACES:
            timestamps = by_tenant_surface.get((tenant_id, surface.key), [])
            last_used = max(timestamps, default=None)
            eligible = surface.removal_eligible(last_used_at=last_used, now=now)
            evidence.append(
                {
                    "key": surface.key,
                    "stage": surface.stage,
                    "hits_30d": sum(value >= cutoff for value in timestamps),
                    "last_used_at": last_used.isoformat() if last_used else None,
                    "observation_started_at": surface.observation_started_at.isoformat(),
                    "eligible_after": surface.eligible_after.isoformat(),
                    "removal_eligible": eligible,
                }
            )
        tenants.append(
            {
                "tenant_id": tenant_id,
                "surfaces": evidence,
                "removal_eligible": all(row["removal_eligible"] for row in evidence),
            }
        )

    eligible = bool(tenants) and all(row["removal_eligible"] for row in tenants)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": now.isoformat(),
        "status": "ELIGIBLE" if eligible else "HOLD",
        "active_tenant_count": len(tenants),
        "all_active_tenants_included": bool(tenants),
        "removal_eligible": eligible,
        "tenants": tenants,
    }
    digest = hmac.new(
        signing_key.encode(), _canonical(payload), hashlib.sha256
    ).hexdigest()
    payload["signature"] = {
        "algorithm": "HMAC-SHA256",
        "key_id": hashlib.sha256(signing_key.encode()).hexdigest()[:16],
        "digest": digest,
    }
    return payload


def verify_signed_removal_report(report: dict[str, Any], *, signing_key: str) -> bool:
    if len(signing_key) < 32:
        return False
    payload = dict(report)
    signature = payload.pop("signature", None)
    if not isinstance(signature, dict) or signature.get("algorithm") != "HMAC-SHA256":
        return False
    expected = hmac.new(
        signing_key.encode(), _canonical(payload), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(str(signature.get("digest") or ""), expected)


def evaluate_stage_transition(
    *,
    surface_key: str,
    current_stage: str,
    target_stage: str,
    report: dict[str, Any],
    signing_key: str,
    tenant_notice_acknowledged: bool,
    rollback_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Authorize only the next lifecycle step; never edit registry code."""
    errors: list[str] = []
    allowed_next = {"observe": "warn", "warn": "disable", "disable": "remove"}
    surface = get_deprecation_surface(surface_key)
    if surface is None:
        errors.append(f"unknown deprecation surface: {surface_key}")
    elif surface.stage != current_stage:
        errors.append(
            f"registry stage for {surface_key} is {surface.stage}, not {current_stage}"
        )
    if allowed_next.get(current_stage) != target_stage:
        errors.append("deprecation stages cannot be skipped or reversed")
    if not verify_signed_removal_report(report, signing_key=signing_key):
        errors.append("all-tenant removal report signature is invalid")
    if not report.get("all_active_tenants_included"):
        errors.append("active tenant enumeration is empty or incomplete")
    tenants = report.get("tenants")
    active_count = report.get("active_tenant_count")
    if (
        not isinstance(tenants, list)
        or not isinstance(active_count, int)
        or active_count <= 0
        or len(tenants) != active_count
    ):
        errors.append("active tenant count does not match signed evidence")
    if not tenant_notice_acknowledged:
        errors.append("tenant communication is not acknowledged")
    selected_rows: list[dict[str, Any]] = []
    if isinstance(tenants, list):
        for tenant in tenants:
            rows = tenant.get("surfaces") if isinstance(tenant, dict) else None
            matches = [
                row
                for row in (rows if isinstance(rows, list) else [])
                if isinstance(row, dict) and row.get("key") == surface_key
            ]
            if len(matches) != 1:
                errors.append(
                    f"tenant evidence must contain exactly one {surface_key} row"
                )
            else:
                selected_rows.append(matches[0])
    if any(row.get("stage") != current_stage for row in selected_rows):
        errors.append("signed tenant evidence does not match the claimed current stage")
    if target_stage in {"disable", "remove"} and (
        not isinstance(tenants, list)
        or len(selected_rows) != len(tenants)
        or any(row.get("removal_eligible") is not True for row in selected_rows)
    ):
        errors.append(
            f"30-day all-tenant zero-traffic gate has not passed for {surface_key}"
        )
    if target_stage == "remove" and (rollback_result or {}).get("status") != "PASS":
        errors.append("operator rollback gate has not passed")
    return {"status": "PASS" if not errors else "HOLD", "errors": errors}
