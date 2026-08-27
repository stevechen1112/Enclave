"""Fail-closed validation for operator-produced modular rollback evidence."""

from __future__ import annotations

import re
from typing import Any

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
PROTECTED_OBJECT_KINDS = {
    "source_asset_original",
    "derived_artifact",
    "evidence_locator",
    "knowledge_unit_revision",
    "legacy_document_file",
    "long_recording_chunk",
    "external_connector_lineage",
}


def evaluate_rollback_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    deployment = evidence.get("deployment") or {}
    if not all(
        deployment.get(key)
        for key in ("manifest_id", "backend_image", "frontend_image", "worker_image")
    ):
        errors.append("deployment identity is incomplete")

    backup = evidence.get("backup_restore") or {}
    for key in ("database_backup_sha256", "object_backup_sha256"):
        if not _SHA256.fullmatch(str(backup.get(key) or "")):
            errors.append(f"{key} must be an exact sha256 digest")
    if (
        backup.get("restore_status") != "PASS"
        or backup.get("isolated_environment") is not True
    ):
        errors.append("isolated backup restore drill has not passed")
    if (
        not isinstance(backup.get("restore_rto_seconds"), int)
        or backup.get("restore_rto_seconds") <= 0
    ):
        errors.append("restore RTO is missing")

    downgrade = evidence.get("database_downgrade") or {}
    if (
        downgrade.get("status") != "PASS"
        or not downgrade.get("from_revision")
        or not downgrade.get("to_revision")
    ):
        errors.append("database downgrade rehearsal has not passed")
    if downgrade.get("new_kind_compatibility_scan") != "PASS":
        errors.append("new artifact-kind compatibility scan has not passed")

    objects = evidence.get("object_store") or {}
    protected = set(objects.get("protected_kinds") or [])
    if (
        objects.get("inventory_status") != "PASS"
        or not PROTECTED_OBJECT_KINDS <= protected
    ):
        errors.append("irreversible object inventory is incomplete")
    if objects.get("deleted_during_drill") not in (0, "0"):
        errors.append("rollback drill deleted durable objects")

    smoke = evidence.get("rollback_smoke") or {}
    required_smokes = ("asset_read", "review", "sealed_retrieval", "tenant_isolation")
    if any(smoke.get(key) != "PASS" for key in required_smokes):
        errors.append("rollback smoke suite is incomplete")
    if not evidence.get("operator") or not evidence.get("completed_at"):
        errors.append("operator attestation is missing")
    return {"status": "PASS" if not errors else "HOLD", "errors": errors}
