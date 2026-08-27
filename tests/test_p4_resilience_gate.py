from __future__ import annotations

import json
from pathlib import Path

from app.services.resilience_gate import (
    REQUIRED_ALERTS,
    REQUIRED_FAULT_SCENARIOS,
    REQUIRED_LIVE_FAULT_SCENARIOS,
    evaluate_p4_resilience_evidence,
)
from app.services.rollback_gate import PROTECTED_OBJECT_KINDS

ROOT = Path(__file__).resolve().parents[1]


def _rollback_evidence() -> dict:
    return {
        "deployment": {
            "manifest_id": "dm-p4",
            "backend_image": "sha256:b",
            "frontend_image": "sha256:f",
            "worker_image": "sha256:w",
        },
        "backup_restore": {
            "database_backup_sha256": "a" * 64,
            "object_backup_sha256": "b" * 64,
            "restore_status": "PASS",
            "isolated_environment": True,
            "restore_rto_seconds": 120,
        },
        "database_downgrade": {
            "status": "PASS",
            "from_revision": "head",
            "to_revision": "n-1",
            "new_kind_compatibility_scan": "PASS",
        },
        "object_store": {
            "inventory_status": "PASS",
            "protected_kinds": sorted(PROTECTED_OBJECT_KINDS),
            "deleted_during_drill": 0,
        },
        "rollback_smoke": {
            "asset_read": "PASS",
            "review": "PASS",
            "sealed_retrieval": "PASS",
            "tenant_isolation": "PASS",
        },
        "operator": "p4-test",
        "completed_at": "2026-08-28T00:00:00Z",
    }


def _complete_evidence() -> dict:
    return {
        "rollback_evidence": _rollback_evidence(),
        "restore_drill": {
            "status": "PASS",
            "isolated_environment": True,
            "source_mutated": False,
            "rto_seconds": 120,
            "rpo_seconds": 1,
            "rto_target_seconds": 900,
            "rpo_target_seconds": 300,
            "database": {
                "backup_status": "PASS",
                "restore_status": "PASS",
                "sha256": "1" * 64,
                "table_count": 10,
            },
            "object_store": {
                "backup_status": "PASS",
                "restore_status": "PASS",
                "sha256": "2" * 64,
                "objects": 4,
                "bytes": 100,
                "restored_objects": 4,
                "restored_bytes": 100,
            },
            "index": {
                "backup_status": "PASS",
                "restore_status": "PASS",
                "sha256": "3" * 64,
                "inventory": "4|4|100",
            },
            "configuration": {
                "backup_status": "PASS",
                "restore_status": "PASS",
                "sha256": "4" * 64,
                "secret_material_included": False,
                "files": 3,
                "bytes": 200,
                "restored_files": 3,
                "restored_bytes": 200,
            },
        },
        "fault_injection": [
            {
                "scenario": name,
                "status": "PASS",
                "execution_class": "live"
                if name in REQUIRED_LIVE_FAULT_SCENARIOS
                else "contract",
                "terminal_state": "recovered",
                "operator_message": "dependency recovered",
                "recovered": True,
                "data_loss": 0,
                "cross_tenant_leak": 0,
                "false_completion": 0,
            }
            for name in sorted(REQUIRED_FAULT_SCENARIOS)
        ],
        "alert_lifecycle": [
            {"alert": name, "fire_status": "PASS", "recover_status": "PASS"}
            for name in sorted(REQUIRED_ALERTS)
        ],
        "runtime_verification": {
            "health_status": "PASS",
            "data_loss": 0,
            "cross_tenant_leak": 0,
            "false_completion": 0,
        },
        "operator": "p4-test",
        "completed_at": "2026-08-28T00:00:00Z",
    }


def test_blank_p4_template_fails_closed():
    evidence = json.loads(
        (ROOT / "docs" / "templates" / "P4_RESILIENCE_EVIDENCE.json").read_text(
            encoding="utf-8"
        )
    )
    result = evaluate_p4_resilience_evidence(evidence)
    assert result["status"] == "HOLD"
    assert result["errors"]


def test_complete_p4_evidence_passes():
    assert evaluate_p4_resilience_evidence(_complete_evidence()) == {
        "status": "PASS",
        "errors": [],
    }


def test_missing_fault_and_alert_fail_closed():
    evidence = _complete_evidence()
    evidence["fault_injection"].pop()
    evidence["alert_lifecycle"].pop()
    result = evaluate_p4_resilience_evidence(evidence)
    assert result["status"] == "HOLD"
    assert any("missing fault scenarios" in error for error in result["errors"])
    assert any("missing alert lifecycle" in error for error in result["errors"])


def test_live_fault_cannot_be_satisfied_by_contract_only_test():
    evidence = _complete_evidence()
    row = next(
        row
        for row in evidence["fault_injection"]
        if row["scenario"] == "redis_unavailable"
    )
    row["execution_class"] = "contract"
    result = evaluate_p4_resilience_evidence(evidence)
    assert result["status"] == "HOLD"
    assert (
        "fault scenario requires live execution: redis_unavailable" in result["errors"]
    )


def test_restore_target_miss_fails_closed():
    evidence = _complete_evidence()
    evidence["restore_drill"]["rto_seconds"] = 901
    result = evaluate_p4_resilience_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "restore RTO target was not met" in result["errors"]


def test_restore_inventory_mismatch_fails_closed():
    evidence = _complete_evidence()
    evidence["restore_drill"]["object_store"]["restored_objects"] = 3
    evidence["restore_drill"]["configuration"]["secret_material_included"] = True
    result = evaluate_p4_resilience_evidence(evidence)
    assert result["status"] == "HOLD"
    assert "restored object inventory differs from backup" in result["errors"]
    assert any("secret material" in error for error in result["errors"])
