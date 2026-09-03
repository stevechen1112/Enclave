"""KQ7 aggregate release gate; external evidence can never be inferred."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.services.knowledge_evaluation_policy import (
    holdout_pair_errors,
    release_threshold_errors,
)
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
    sealed_runs: Iterable[Any],
    release_identity: KnowledgeReleaseIdentity,
    authorization_store: AuthorizationStore,
    candidate_tenants: Iterable[str],
    enforce_tenants: Iterable[str],
    shadow_evidence: Mapping[str, Any],
    rollback_evidence: Mapping[str, Any],
    browser_acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    runs = list(sealed_runs)
    reasons = list(holdout_pair_errors(runs))
    for index, run in enumerate(runs):
        reasons.extend(
            f"sealed_{index}.{reason}"
            for reason in release_threshold_errors(run.summary_json or {}, stage)
        )
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

    authorizations: dict[str, dict[str, str]] = {}
    for tenant in candidate_tenants:
        shadow = authorization_store.active_authorization(
            tenant_id=tenant,
            requested_mode="shadow",
            release_identity=release_identity,
        )
        if shadow is None:
            reasons.append(f"authorization.shadow_missing:{tenant}")
        else:
            authorizations.setdefault(tenant, {})["shadow"] = shadow.authorization_id
    for tenant in enforce_tenants:
        enforce = authorization_store.active_authorization(
            tenant_id=tenant,
            requested_mode="enforce",
            release_identity=release_identity,
        )
        if enforce is None:
            reasons.append(f"authorization.enforce_missing:{tenant}")
        else:
            authorizations.setdefault(tenant, {})["enforce"] = enforce.authorization_id

    return {
        "schema_version": "kq-release-gate/v1",
        "gate": "KQ-RELEASE-01",
        "stage": stage,
        "status": "PASS" if not reasons else "BLOCKED",
        "release_identity_hash": release_identity.identity_hash,
        "sealed_first_runs": len(runs),
        "tenant_authorizations": authorizations,
        "reasons": sorted(set(reasons)),
    }
