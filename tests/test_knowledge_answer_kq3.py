from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.config import Settings, settings
from app.services.knowledge_decision_shadow import (
    EncryptedAppendOnlyShadowStore,
    ShadowDiffRecord,
    resolve_knowledge_decision_mode,
    run_knowledge_decision_shadow,
    summarize_shadow_records,
)


@pytest.fixture(autouse=True)
def _legacy_kq3_shadow_authorization_compatibility(monkeypatch):
    """KQ3 predates KQ7 signed authorization; enforce remains fail closed."""
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_AUTHORIZATION_REQUIRED", False)


def _record(tenant_ref="tenant-ref", **changes):
    values = {
        "record_id": str(uuid4()),
        "schema_version": "kq-shadow.v1",
        "captured_at": "2026-09-03T11:00:00+00:00",
        "tenant_ref": tenant_ref,
        "request_ref": "request-ref",
        "channel": "sync",
        "legacy_decision": "answer",
        "new_evidence_state": "insufficient_context",
        "new_response_action": "clarify",
        "execution_status": "ok",
        "decision_hash": "d" * 64,
        "transition": "answer->insufficient_context",
        "false_accept_candidate": False,
        "false_reject_candidate": True,
        "stage_trace": [{"stage": "parse", "status": "ok"}],
        "reason_codes": ["completeness.insufficient_context"],
        "source_refs": [{"document_id": "doc-a", "document_revision": "1"}],
        "stage_latency_ms": {"parse": 1.0, "retrieve": 2.0, "render": None},
    }
    values.update(changes)
    return ShadowDiffRecord(**values)


def test_kq3_flags_default_off_normalize_and_reject_invalid():
    configured = Settings(_env_file=None)
    assert configured.KNOWLEDGE_DECISION_MODE == "off"
    assert configured.KNOWLEDGE_DECISION_TENANT_ALLOWLIST == ""
    assert configured.KNOWLEDGE_DECISION_KILL_SWITCH is False
    assert Settings(_env_file=None, KNOWLEDGE_DECISION_MODE=" ShAdOw ").KNOWLEDGE_DECISION_MODE == "shadow"
    with pytest.raises(ValueError, match="KNOWLEDGE_DECISION_MODE"):
        Settings(_env_file=None, KNOWLEDGE_DECISION_MODE="audit")


def test_allowlist_kill_switch_and_unapproved_enforce_fail_closed(monkeypatch):
    tenant = str(uuid4())
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_TENANT_ALLOWLIST", tenant)
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_KILL_SWITCH", False)
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_MODE", "shadow")
    assert resolve_knowledge_decision_mode(tenant) == "shadow"
    assert resolve_knowledge_decision_mode(uuid4()) == "off"
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_MODE", "enforce")
    assert resolve_knowledge_decision_mode(tenant) == "off"
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_MODE", "shadow")
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_KILL_SWITCH", True)
    assert resolve_knowledge_decision_mode(tenant) == "off"


def test_encrypted_store_is_append_only_tenant_scoped_and_reauthorizes_sources(tmp_path):
    store = EncryptedAppendOnlyShadowStore(tmp_path, key="test-key")
    tenant = "tenant-a"
    from app.services.knowledge_decision_shadow import _tenant_ref

    record = _record(_tenant_ref(tenant))
    path = store.append(record)
    raw = path.read_text(encoding="utf-8")
    assert record.decision_hash not in raw
    assert "doc-a" not in raw
    with pytest.raises(ValueError, match="already exists"):
        store.append(record)
    with pytest.raises(PermissionError):
        store.read_for_tenant(tenant, actor_roles=["member"])
    assert store.read_for_tenant("tenant-b", actor_roles=["admin"]) == []
    rows = store.read_for_tenant(
        tenant,
        actor_roles=["auditor"],
        source_authorizer=lambda ref: ref.get("document_id") != "doc-a",
    )
    assert len(rows) == 1 and rows[0]["source_refs"] == []


def test_retention_purge_preserves_legal_hold_and_writes_content_free_audit(tmp_path):
    store = EncryptedAppendOnlyShadowStore(tmp_path, key="test-key")
    old = _record(captured_at="2026-01-01T00:00:00+00:00")
    store.append(old)
    assert store.purge_expired(
        now=datetime(2026, 9, 3, tzinfo=timezone.utc),
        retention_days=30,
        legal_hold_record_ids=[old.record_id],
    ) == []
    purged = store.purge_expired(
        now=datetime(2026, 9, 3, tzinfo=timezone.utc), retention_days=30
    )
    assert purged == ["shadow-2026-01-01.jsonl.enc"]
    audit = (tmp_path / "purge-audit.jsonl").read_text(encoding="utf-8")
    assert "doc-a" not in audit and "retention_purge" in audit


def test_off_mode_executes_no_decision_or_writer(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_MODE", "off")
    result = run_knowledge_decision_shadow(
        tenant_id="tenant-a",
        request_id="request-a",
        query_plan={},
        results=[],
        legacy_coverage={"decision": "abstain"},
    )
    assert result == {
        "mode": "off",
        "executed": False,
        "telemetry_status": "not_attempted",
    }
    assert not list(tmp_path.iterdir())


def test_shadow_writer_failure_never_raises_or_changes_legacy_decision(monkeypatch):
    tenant = "tenant-a"
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_MODE", "shadow")
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_TENANT_ALLOWLIST", tenant)
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_KILL_SWITCH", False)

    class BrokenStore:
        def append(self, record):
            raise OSError("telemetry unavailable")

    legacy = {"decision": "answer", "covered_slots": ["answer"]}
    result = run_knowledge_decision_shadow(
        tenant_id=tenant,
        request_id="request-a",
        query_plan={},
        results=[{"content": "private answer", "metadata": {}}],
        legacy_coverage=legacy,
        store=BrokenStore(),
    )
    assert legacy["decision"] == "answer"
    assert result["telemetry_status"] == "failed"
    assert result["error_class"] == "OSError"


def test_legacy_retrieval_result_without_new_authority_metadata_is_not_false_rejected(
    monkeypatch, tmp_path
):
    tenant = "tenant-a"
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_MODE", "shadow")
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_TENANT_ALLOWLIST", tenant)
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_KILL_SWITCH", False)
    result = run_knowledge_decision_shadow(
        tenant_id=tenant,
        request_id="legacy-result",
        query_plan={"requested_slots": ["answer"], "operation": "lookup"},
        results=[
            {
                "id": "chunk-1",
                "document_id": "doc-1",
                "document_revision": "1",
                "content": "已由可信任檢索層核准的既有文件內容",
                "metadata": {},
            }
        ],
        legacy_coverage={"decision": "answer"},
        store=EncryptedAppendOnlyShadowStore(tmp_path, key="test-key"),
    )
    assert result["evidence_state"] == "complete"
    assert result["false_accept_candidate"] is False
    assert result["false_reject_candidate"] is False


def test_transition_candidate_labels_follow_acceptance_semantics(monkeypatch, tmp_path):
    tenant = "tenant-a"
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_MODE", "shadow")
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_TENANT_ALLOWLIST", tenant)
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_KILL_SWITCH", False)
    store = EncryptedAppendOnlyShadowStore(tmp_path, key="test-key")
    accepted = run_knowledge_decision_shadow(
        tenant_id=tenant,
        request_id="newly-accepted",
        query_plan={"requested_slots": ["answer"]},
        results=[{"id": "c1", "document_id": "d1", "content": "answer"}],
        legacy_coverage={"decision": "abstain"},
        store=store,
    )
    assert accepted["false_accept_candidate"] is True
    assert accepted["false_reject_candidate"] is False
    rejected = run_knowledge_decision_shadow(
        tenant_id=tenant,
        request_id="newly-rejected",
        query_plan={"requested_slots": ["answer"]},
        results=[
            {
                "id": "c2",
                "document_id": "d2",
                "content": "answer",
                "metadata": {"active_revision": False},
            }
        ],
        legacy_coverage={"decision": "answer"},
        store=store,
    )
    assert rejected["false_accept_candidate"] is False
    assert rejected["false_reject_candidate"] is True


@pytest.mark.asyncio
async def test_sync_and_stream_share_retrieve_context_shadow_adapter(monkeypatch, tmp_path):
    tenant = uuid4()
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_MODE", "shadow")
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_TENANT_ALLOWLIST", str(tenant))
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_KILL_SWITCH", False)
    monkeypatch.setattr(settings, "KNOWLEDGE_DECISION_SHADOW_STORE_PATH", str(tmp_path))

    async def fake_run(self, **kwargs):
        return {
            "status": "success",
            "has_evidence": True,
            "results": [
                {
                    "id": "r1",
                    "content": "設備狀態為可使用",
                    "filename": "manual.pdf",
                    "document_id": "doc-a",
                    "document_revision": "1",
                    "score": 1.0,
                    "metadata": {
                        "active_revision": True,
                        "release_active": True,
                        "quality_ready": True,
                    },
                }
            ],
            "catalog_hits": [],
            "clause_projections": [],
            "query_plan": {
                "plan_version": "2.0",
                "operation": "lookup",
                "requested_slots": ["status"],
                "completeness_mode": "best_effort",
            },
        }

    from app.services import multi_step_orchestrator
    from app.services.chat_orchestrator import ChatOrchestrator

    monkeypatch.setattr(multi_step_orchestrator.MultiStepOrchestrator, "run", fake_run)
    orchestrator = ChatOrchestrator()
    context = await orchestrator.retrieve_context(
        tenant_id=tenant, question="狀態？", authz=object()
    )
    assert context["knowledge_decision_shadow"]["executed"] is True
    assert context["knowledge_decision_shadow"]["telemetry_status"] == "written"
    assert "retrieve_context" in inspect.getsource(ChatOrchestrator.process_query)
    # stream endpoint also calls retrieve_context before stream_answer.
    from app.api.v1.endpoints import chat

    assert "retrieve_context" in inspect.getsource(chat.chat_stream)


def test_threshold_manifest_was_frozen_before_formal_first_run():
    from pathlib import Path

    path = Path("artifacts/knowledge/KQ_SHADOW_THRESHOLD_MANIFEST_V1.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["immutable"] is True
    assert payload["case_manifest"]["minimum_cases"] >= 30
    assert payload["case_manifest"]["minimum_deny_or_forbidden_cases"] >= 4
    assert payload["quality_thresholds"]["minimum_sync_stream_decision_parity"] == 1.0


def test_shadow_metrics_keep_false_accept_reject_and_stage_latency_separate():
    rows = [
        _record(false_accept_candidate=True, false_reject_candidate=False).__dict__,
        _record(false_accept_candidate=False, false_reject_candidate=True, transition="abstain->complete").__dict__,
        _record(execution_status="timeout").__dict__,
    ]
    summary = summarize_shadow_records(rows)
    assert summary["valid_cases"] == 2
    assert summary["false_accept_rate"] == 0.5
    assert summary["false_reject_rate"] == 0.5
    assert summary["transition_matrix"] == {
        "abstain->complete": 1,
        "answer->insufficient_context": 1,
    }
    assert summary["stage_latency_ms"]["retrieve"]["p95"] == 2.0


def test_authorized_read_only_view_is_registered_and_rechecks_sources():
    from app.api.v1.endpoints import knowledge_decision
    from app.api.v1.endpoints.knowledge_decision import list_knowledge_decision_diffs

    paths = {route.path for route in knowledge_decision.router.routes}
    assert "/knowledge/decision-diffs" in paths
    source = inspect.getsource(list_knowledge_decision_diffs)
    assert "Document.tenant_id == current_user.tenant_id" in source
    assert "Document.tombstoned_at.is_(None)" in source
    assert '"read_only": True' in source


def test_production_compose_persists_shadow_store_outside_tenant_db():
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "knowledge_shadow_data:/var/lib/enclave/knowledge-shadow" in compose
    assert "KNOWLEDGE_DECISION_SHADOW_STORE_PATH=/var/lib/enclave/knowledge-shadow" in compose
    assert "knowledge_shadow_data:" in compose


def test_production_example_keeps_shadow_disabled_and_key_unset():
    root = Path(__file__).resolve().parents[1]
    env_example = (root / ".env.production.example").read_text(encoding="utf-8")
    normalized = env_example.replace("\r\n", "\n")
    assert "KNOWLEDGE_DECISION_MODE=off" in normalized
    assert "KNOWLEDGE_DECISION_TENANT_ALLOWLIST=" in normalized
    assert "KNOWLEDGE_DECISION_KILL_SWITCH=false" in normalized
    assert "KNOWLEDGE_DECISION_SHADOW_KEY=\n" in normalized
