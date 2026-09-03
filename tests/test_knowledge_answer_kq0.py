import hashlib
import json
from pathlib import Path

from scripts import freeze_knowledge_answer_baseline as baseline


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "knowledge"


def _read(name: str):
    return json.loads((ARTIFACT_DIR / name).read_text(encoding="utf-8"))


def test_kq0_behavior_matrix_covers_all_required_shapes_without_provider_or_db():
    snapshot = baseline.behavior_snapshot()
    assert snapshot["case_count"] >= 13
    assert set(snapshot["categories"]) >= {
        "direct_fact",
        "exhaustive_list",
        "partial_answer",
        "absent_answer",
        "insufficient_context",
        "conflict",
        "comparison",
        "procedure",
        "table_same_row",
        "wrong_scope",
        "wrong_revision",
        "provider_failure",
        "multi_turn",
    }
    assert "no DB, provider" in snapshot["harness"]
    assert all(case["sync_stream_fallback_equal"] for case in snapshot["cases"])


def test_kq0_baseline_preserves_the_current_known_decision_failures():
    cases = {item["case_id"]: item for item in baseline.behavior_snapshot()["cases"]}
    assert cases["KQ0-insufficient-context"]["legacy_decision"]["decision"] == "answer"
    assert cases["KQ0-conflict"]["legacy_decision"]["decision"] == "answer"
    assert cases["KQ0-wrong-scope"]["legacy_decision"]["decision"] == "answer"
    assert cases["KQ0-wrong-revision"]["legacy_decision"]["decision"] == "answer"
    assert cases["KQ0-provider-failure"]["legacy_decision"]["decision"] == "abstain"


def test_kq0_api_contract_and_static_call_graph_are_complete():
    contract = baseline.api_contract_snapshot()
    assert contract["sync"]["path"] == "/chat"
    assert contract["stream"]["path"] == "/chat/stream"
    assert set(contract["stream"]["events"]) == {
        "status",
        "retrieval",
        "sources",
        "token",
        "suggestions",
        "done",
        "error",
    }
    assert set(contract["sync"]["response_schema"]["required"]) >= {
        "request_id",
        "question",
        "answer",
        "conversation_id",
        "message_id",
        "sources",
    }

    graph = baseline.call_graph_snapshot()
    assert graph["status"] == "PASS"
    assert graph["decision_owners"]["live"].endswith("assess_retrieval_coverage")
    assert graph["decision_owners"]["offline_only"].endswith("decide_evidence")
    assert len(graph["edges"]) >= 15
    assert all((ROOT / edge["source_ref"]["path"]).is_file() for edge in graph["edges"])


def test_kq0_contamination_scan_has_no_unwaived_runtime_findings():
    scan = baseline.contamination_snapshot()
    assert scan["status"] == "PASS"
    assert scan["findings"] == []
    assert any(item["waiver_id"] == "KQ0-WAIVER-LEGACY-HR-001" for item in scan["waivers"])
    assert baseline._looks_like_full_question("這是一個不應出現在核心條件分支裡面的完整測試問題嗎？")
    assert not baseline._looks_like_full_question(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


def test_kq0_artifact_manifest_hashes_and_gate_status_are_honest():
    manifest = _read("KQ_BASELINE_MANIFEST.json")
    assert manifest["gate"] == "KQ-BL-01"
    assert manifest["status"] == "BLOCKED"
    assert manifest["next_allowed_action"].endswith("do not start KQ1")
    checks = {item["name"]: item["status"] for item in manifest["gate_checks"]}
    assert checks["offline_case_matrix_complete"] == "PASS"
    assert checks["core_contamination_zero_unwaived"] == "PASS"
    assert checks["production_snapshot_fresh"] == "BLOCKED"
    assert checks["exact_kb_knowledge_release_pack_versions_frozen"] == "BLOCKED"
    for record in manifest["artifacts"]:
        path = ROOT / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_kq0_known_failures_have_unique_ids_and_phase_owners():
    failures = _read("KQ_KNOWN_FAILURES.json")["failures"]
    ids = [item["id"] for item in failures]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 10
    assert all(item["target_phase"].startswith("KQ") for item in failures)
    assert {"KQ0-KF-001", "KQ0-KF-004", "KQ0-KF-006"} <= set(ids)
