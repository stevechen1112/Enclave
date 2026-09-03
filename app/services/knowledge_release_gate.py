"""KQ7 technical release gate.

Independent holdouts and customer paperwork may be run as optional QA and
governance activities, but they are deliberately not development blockers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.services.knowledge_release_control import (
    AuthorizationStore,
    KnowledgeReleaseIdentity,
)


def rollback_drill_errors(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    if not bool(evidence.get("kill_switch_verified")):
        errors.append("rollback.kill_switch_not_verified")
    if not bool(evidence.get("legacy_path_restored")):
        errors.append("rollback.legacy_path_not_restored")
    if int(evidence.get("knowledge_mutations") or 0) != 0:
        errors.append("rollback.knowledge_mutation_detected")
    sla = float(evidence.get("ask_sla_p95_ms") or 0)
    restored = float(evidence.get("restored_path_p95_ms") or 0)
    if sla <= 0 or restored <= 0 or restored > sla:
        errors.append("rollback.restored_path_sla_failed")
    if len(str(evidence.get("evidence_sha256") or "")) != 64:
        errors.append("rollback.evidence_digest_missing")
    return tuple(errors)


def evaluate_kq7_release_gate(
    *,
    stage: str,
    sealed_runs: Iterable[Any] = (),
    release_identity: KnowledgeReleaseIdentity,
    authorization_store: AuthorizationStore | None = None,
    candidate_tenants: Iterable[str] = (),
    enforce_tenants: Iterable[str] = (),
    shadow_evidence: Mapping[str, Any],
    rollback_evidence: Mapping[str, Any],
    browser_acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    runs = list(sealed_runs)
    reasons: list[str] = []
    reasons.extend(rollback_drill_errors(rollback_evidence))
    if (
        shadow_evidence.get("knowledge_mutations") is None
        or int(shadow_evidence["knowledge_mutations"]) != 0
    ):
        reasons.append("shadow.mutation_count_not_zero")
    if not bool(shadow_evidence.get("sync_stream_parity")):
        reasons.append("shadow.sync_stream_parity_failed")
    if len(str(shadow_evidence.get("evidence_sha256") or "")) != 64:
        reasons.append("shadow.evidence_digest_missing")
    if (
        not bool(browser_acceptance.get("passed"))
        or len(str(browser_acceptance.get("evidence_sha256") or "")) != 64
    ):
        reasons.append("browser.acceptance_missing_or_failed")
    if release_identity.errors():
        reasons.extend(release_identity.errors())

    # Retain optional evidence counts for observability only. They never alter
    # the technical release verdict.
    optional_governance = {
        "sealed_first_runs": len(runs),
        "candidate_tenants": len(tuple(candidate_tenants)),
        "enforce_tenants": len(tuple(enforce_tenants)),
        "authorization_store_configured": authorization_store is not None,
    }

    return {
        "schema_version": "kq-release-gate/v1",
        "gate": "KQ-RELEASE-01",
        "stage": stage,
        "status": "PASS" if not reasons else "BLOCKED",
        "release_identity_hash": release_identity.identity_hash,
        "optional_governance": optional_governance,
        "reasons": sorted(set(reasons)),
    }
