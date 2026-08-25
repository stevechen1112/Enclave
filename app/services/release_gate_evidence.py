"""Validation of server-generated, revision-bound release evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


REQUIRED_PROMOTION_GATES = {
    "KB-BL-01": "baseline_gate_last_run.json",
    "KB-INGEST-01": "ingest_gate_last_run.json",
    "KB-REV-01": "revision_gate_last_run.json",
    "KB-QSPEC-01": "queryspec_gate_last_run.json",
    "KB-ROW-01": "row_gate_last_run.json",
    "KB-PROC-01": "procedure_gate_last_run.json",
    "KB-EVIDENCE-01": "evidence_gate_last_run.json",
    "KB-AUTH-01": "authority_gate_last_run.json",
    "KB-EVAL-01": "evaluation_gate_last_run.json",
    "KB-SCALE-01": "capacity_profile_last_run.json",
    "KB-UX-01": "browser_acceptance_last_run.json",
    "KB-SHADOW-01": "shadow_last_run.json",
    "KB-OPS-01": "operations_gate_last_run.json",
}


def load_revision_gate_evidence(
    artifact_root: Path,
    *,
    revision_id: str,
    manifest_hash: str,
    required: Iterable[str] = REQUIRED_PROMOTION_GATES,
) -> dict[str, str]:
    """Return PASS only when the artifact belongs to this exact candidate.

    A stale PASS from another tenant, revision or manifest must never release a
    candidate.  The browser cannot supply or override these fields.
    """
    return {gate: "PASS" for gate in load_revision_gate_artifacts(
        artifact_root, revision_id=revision_id, manifest_hash=manifest_hash, required=required
    )}


def load_revision_gate_artifacts(
    artifact_root: Path,
    *,
    revision_id: str,
    manifest_hash: str,
    required: Iterable[str] = REQUIRED_PROMOTION_GATES,
) -> dict[str, dict]:
    """Load the immutable evidence payloads after common binding checks."""
    evidence: dict[str, dict] = {}
    for gate in required:
        filename = REQUIRED_PROMOTION_GATES.get(gate)
        if filename is None:
            continue
        try:
            data = json.loads((artifact_root / filename).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if (
            data.get("schema_version") == 1
            and data.get("gate") == gate
            and data.get("status") == "PASS"
            and str(data.get("revision_id")) == revision_id
            and data.get("manifest_hash") == manifest_hash
        ):
            evidence[gate] = data
    return evidence
