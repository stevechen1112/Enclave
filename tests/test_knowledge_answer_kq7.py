from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.config import settings
from app.services.evidence_contract import ExecutionStatus
from app.services.evidence_orchestrator import decide_evidence
from app.services.knowledge_decision_shadow import resolve_knowledge_decision_mode
from app.services.knowledge_evaluation_policy import (
    classification_quality,
    holdout_pair_errors,
    release_threshold_errors,
    stage_trace_errors,
    validate_regression_manifest,
)
from app.services.knowledge_release_control import (
    AuthorizationStore,
    KnowledgeReleaseIdentity,
    TenantDecisionAuthorization,
    request_is_in_authorized_traffic,
)
from app.services.knowledge_release_gate import (
    evaluate_kq7_release_gate,
    rollback_drill_errors,
)
from tests.test_knowledge_answer_kq6 import _contract, _evidence


def _identity(*, release: str = "release-1") -> KnowledgeReleaseIdentity:
    return KnowledgeReleaseIdentity(
        backend_image_digest="sha256:" + "a" * 64,
        frontend_image_digest="sha256:" + "b" * 64,
        deployment_manifest_id="dm-" + "c" * 24,
        kb_revision_id="kb-revision-1",
        knowledge_release_id=release,
        pack_versions={"hr_knowledge": "1.0.0", "manufacturing_knowledge": "1.0.0"},
        prompt_version="answer-plan-v1",
        model_id="gpt-test",
        rollback_point="legacy-decision-path",
    )


def _authorization(
    tenant: str,
    mode: str,
    identity: KnowledgeReleaseIdentity,
    *,
    now: datetime | None = None,
) -> TenantDecisionAuthorization:
    point = now or datetime.now(timezone.utc)
    prerequisite = (
        {
            key: str(index) * 64
            for index, key in enumerate(
                (
                    "shadow_gate",
                    "tenant_acceptance",
                    "acl_negative",
                    "rollback_drill",
                    "browser_acceptance",
                ),
                start=1,
            )
        }
        if mode == "enforce"
        else {}
    )
    return TenantDecisionAuthorization(
        authorization_id=str(uuid4()),
        tenant_id=tenant,
        mode=mode,
        scope=("ask",),
        traffic_percent=100,
        not_before=(point - timedelta(minutes=1)).isoformat(),
        expires_at=(point + timedelta(days=1)).isoformat(),
        release_identity=asdict(identity),
        release_identity_hash=identity.identity_hash,
        data_use_scope=("tenant_knowledge",),
        rollback_owner="operator@example.invalid",
        stop_conditions=("critical_error", "p95_sla_breach", "kill_switch"),
        owner_id="tenant-owner@example.invalid",
        issued_at=point.isoformat(),
        prerequisite_evidence=prerequisite,
    )


def _passing_summary(rate: float = 0.95) -> dict:
    return {
        "total": 200,
        "strict_assertions": {"rate": rate},
        "critical_errors": 0,
        "domain_distribution": {
            name: 50 for name in ("hr", "manufacturing", "legal", "operations")
        },
        "domain_quality": {
            name: {"denominator": 50, "rate": rate}
            for name in ("hr", "manufacturing", "legal", "operations")
        },
        "required_slot_coverage": {"denominator": 400, "rate": 0.99},
        "language_profile_distribution": {"standard": 160, "mixed": 40},
        "pipeline_invariant_violations": 0,
        "classification_quality": {
            name: {"numerator": 0, "denominator": 10, "rate": 0.0}
            for name in (
                "false_acceptance",
                "false_rejection",
                "partial_correctness",
                "conflict_correctness",
            )
        },
    }


def test_six_stage_trace_is_complete_and_ordered():
    decision = decide_evidence(_contract("t1"), [_evidence("t1")])
    assert stage_trace_errors(decision.stage_trace) == ()
    assert stage_trace_errors(decision.stage_trace[:-1]) == (
        "pipeline_stage_order_or_membership_invalid",
    )


def test_alpha_beta_ga_thresholds_and_critical_error_are_fail_closed():
    assert release_threshold_errors(_passing_summary(0.85), "internal_alpha") == ()
    assert release_threshold_errors(_passing_summary(0.90), "external_beta") == ()
    assert release_threshold_errors(_passing_summary(0.95), "ga") == ()
    failed = _passing_summary(0.95)
    failed["critical_errors"] = 1
    assert "critical_error_present" in release_threshold_errors(failed, "ga")


def test_false_rates_are_separate_and_execution_failures_are_not_safe_refusals():
    rows = [
        {
            "metrics": {
                "expected_class": "absent",
                "actual_class": "answer",
                "execution_status": "ok",
            }
        },
        {
            "metrics": {
                "expected_class": "answer",
                "actual_class": "abstain",
                "execution_status": "ok",
            }
        },
        {
            "metrics": {
                "expected_class": "partial",
                "actual_class": "partial",
                "execution_status": "ok",
            }
        },
        {
            "metrics": {
                "expected_class": "conflict",
                "actual_class": "conflict",
                "execution_status": "ok",
            }
        },
        {
            "metrics": {
                "expected_class": "absent",
                "actual_class": "abstain",
                "execution_status": ExecutionStatus.PACK_FAILURE.value,
            }
        },
    ]
    quality = classification_quality(rows)
    assert quality["false_acceptance"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
        "kind": "error_rate",
    }
    assert quality["false_rejection"]["numerator"] == 1
    assert quality["partial_correctness"]["rate"] == 1.0
    assert quality["conflict_correctness"]["rate"] == 1.0


def test_disclosed_aihr_cases_can_only_be_regression_or_neighbor():
    good = [
        {
            "split": "regression",
            "disclosure_status": "disclosed",
            "source_reference": "AIHR-legacy-manifest",
        }
    ]
    assert validate_regression_manifest(good) == ()
    bad = [
        {
            "split": "sealed",
            "disclosure_status": "disclosed",
            "source_reference": "AIHR-legacy-manifest",
        }
    ]
    assert "disclosed_case_mislabeled_sealed:0" in validate_regression_manifest(bad)


def test_two_holdouts_require_nonoverlap_independent_attestation_and_first_run():
    def run(corpus: str, questions: str, custodian: str):
        return SimpleNamespace(
            corpus_hash=corpus,
            question_hash=questions,
            first_run=True,
            runtime_manifest={
                "implementer": "implementation-team",
                "holdout_seal": {
                    "custodian": custodian,
                    "corpus_manifest_sha256": corpus,
                    "questions_sha256": questions,
                    "attestation_sha256": "e" * 64,
                },
            },
        )

    assert (
        holdout_pair_errors(
            [
                run("a" * 64, "b" * 64, "custodian-a"),
                run("c" * 64, "d" * 64, "custodian-b"),
            ]
        )
        == ()
    )
    errors = holdout_pair_errors(
        [
            run("a" * 64, "b" * 64, "custodian-a"),
            run("a" * 64, "d" * 64, "implementation-team"),
        ]
    )
    assert "holdout_corpora_overlap" in errors
    assert "holdout_custodian_not_independent:1" in errors


def test_signed_authorizations_are_immutable_tenant_scoped_and_release_bound(tmp_path):
    identity = _identity()
    store = AuthorizationStore(tmp_path, key="owner-signing-key")
    record = _authorization("tenant-a", "shadow", identity)
    path = store.append(record)
    assert (
        store.active_authorization(
            tenant_id="tenant-a", requested_mode="shadow", release_identity=identity
        )
        == record
    )
    assert (
        store.active_authorization(
            tenant_id="tenant-b", requested_mode="shadow", release_identity=identity
        )
        is None
    )
    assert (
        store.active_authorization(
            tenant_id="tenant-a", requested_mode="enforce", release_identity=identity
        )
        is None
    )
    assert (
        store.active_authorization(
            tenant_id="tenant-a",
            requested_mode="shadow",
            release_identity=_identity(release="release-2"),
        )
        is None
    )
    audit = json.loads(
        (tmp_path / "authorization-audit.jsonl").read_text(encoding="utf-8")
    )
    assert audit["previous_event_hash"] == "0" * 64
    assert len(audit["event_hash"]) == 64
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["record"]["traffic_percent"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        store.active_authorization(
            tenant_id="tenant-a", requested_mode="shadow", release_identity=identity
        )
        is None
    )


def test_authorization_id_cannot_escape_store(tmp_path):
    identity = _identity()
    record = _authorization("tenant-a", "shadow", identity)
    unsafe = TenantDecisionAuthorization(
        **{**record.unsigned_payload(), "authorization_id": "../escape"}
    )
    store = AuthorizationStore(tmp_path, key="owner-signing-key")
    try:
        store.append(unsafe)
    except ValueError as exc:
        assert "unsafe" in str(exc)
    else:
        raise AssertionError("unsafe authorization id was accepted")


def test_shadow_and_enforce_need_distinct_owner_records_and_kill_switch_wins(
    monkeypatch, tmp_path
):
    tenant = "tenant-a"
    identity = _identity()
    store = AuthorizationStore(tmp_path, key="owner-signing-key")
    store.append(_authorization(tenant, "shadow", identity))
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_MODE", "shadow")
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_TENANT_ALLOWLIST", tenant)
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_KILL_SWITCH", False)
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_AUTHORIZATION_REQUIRED", True)
    monkeypatch.setattr(
        settings, "KNOWLEDGE_DECISION_AUTHORIZATION_STORE_PATH", str(tmp_path)
    )
    monkeypatch.setattr(
        settings, "KNOWLEDGE_DECISION_AUTHORIZATION_KEY", "owner-signing-key"
    )

    from app.services import knowledge_release_control

    monkeypatch.setattr(
        knowledge_release_control,
        "current_knowledge_release_identity",
        lambda: identity,
    )
    assert resolve_knowledge_decision_mode(tenant) == "shadow"
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_MODE", "enforce")
    assert resolve_knowledge_decision_mode(tenant) == "off"
    store.append(_authorization(tenant, "enforce", identity))
    assert resolve_knowledge_decision_mode(tenant) == "enforce"
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_KILL_SWITCH", True)
    assert resolve_knowledge_decision_mode(tenant) == "off"


def test_authorized_traffic_is_stable_and_missing_request_key_fails_closed():
    identity = _identity()
    record = _authorization("tenant-a", "enforce", identity)
    limited = TenantDecisionAuthorization(
        **{**record.unsigned_payload(), "traffic_percent": 10}
    )
    first = [
        request_is_in_authorized_traffic(limited, f"request-{index}")
        for index in range(1000)
    ]
    second = [
        request_is_in_authorized_traffic(limited, f"request-{index}")
        for index in range(1000)
    ]
    assert first == second
    assert 60 <= sum(first) <= 140
    assert request_is_in_authorized_traffic(limited, None) is False


def test_rollback_drill_requires_kill_switch_legacy_path_zero_mutation_and_sla():
    passed = {
        "kill_switch_verified": True,
        "legacy_path_restored": True,
        "knowledge_mutations": 0,
        "ask_sla_p95_ms": 1000,
        "restored_path_p95_ms": 900,
        "evidence_sha256": "a" * 64,
    }
    assert rollback_drill_errors(passed) == ()
    failed = {**passed, "knowledge_mutations": 1, "restored_path_p95_ms": 1100}
    assert "rollback.knowledge_mutation_detected" in rollback_drill_errors(failed)
    assert "rollback.restored_path_sla_failed" in rollback_drill_errors(failed)


def test_aggregate_release_gate_never_infers_missing_external_evidence(tmp_path):
    identity = _identity()
    report = evaluate_kq7_release_gate(
        stage="ga",
        sealed_runs=[],
        release_identity=identity,
        authorization_store=AuthorizationStore(tmp_path, key="key"),
        candidate_tenants=["internal", "eight-rules"],
        enforce_tenants=["eight-rules"],
        shadow_evidence={},
        rollback_evidence={},
        browser_acceptance={},
    )
    assert report["status"] == "BLOCKED"
    assert "exactly_two_holdouts_required" in report["reasons"]
    assert "authorization.shadow_missing:eight-rules" in report["reasons"]
    assert "authorization.enforce_missing:eight-rules" in report["reasons"]


def test_aggregate_release_gate_passes_only_with_complete_bound_evidence(tmp_path):
    identity = _identity()
    store = AuthorizationStore(tmp_path, key="key")
    store.append(_authorization("tenant-a", "shadow", identity))
    store.append(_authorization("tenant-a", "enforce", identity))

    def sealed(corpus: str, questions: str, custodian: str):
        return SimpleNamespace(
            corpus_hash=corpus,
            question_hash=questions,
            first_run=True,
            summary_json=_passing_summary(0.95),
            runtime_manifest={
                "implementer": "implementation-team",
                "holdout_seal": {
                    "custodian": custodian,
                    "corpus_manifest_sha256": corpus,
                    "questions_sha256": questions,
                    "attestation_sha256": "f" * 64,
                },
            },
        )

    report = evaluate_kq7_release_gate(
        stage="ga",
        sealed_runs=[
            sealed("a" * 64, "b" * 64, "custodian-a"),
            sealed("c" * 64, "d" * 64, "custodian-b"),
        ],
        release_identity=identity,
        authorization_store=store,
        candidate_tenants=["tenant-a"],
        enforce_tenants=["tenant-a"],
        shadow_evidence={
            "knowledge_mutations": 0,
            "sync_stream_parity": True,
            "evidence_sha256": "1" * 64,
        },
        rollback_evidence={
            "kill_switch_verified": True,
            "legacy_path_restored": True,
            "knowledge_mutations": 0,
            "ask_sla_p95_ms": 1000,
            "restored_path_p95_ms": 900,
            "evidence_sha256": "2" * 64,
        },
        browser_acceptance={"passed": True, "evidence_sha256": "3" * 64},
    )
    assert report["status"] == "PASS"
    assert report["reasons"] == []
