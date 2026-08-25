from scripts.eval_knowledge_operations_gate import validate_operator_evidence


def _evidence():
    return {
        "image_digest": "sha256:" + "a" * 64,
        "revision_id": "revision-1",
        "manifest_hash": "manifest-1",
        "operator": {"id": "sre-a", "role": "sre", "attestation_sha256": "b" * 64},
        "feedback": {"sampled": 10, "missing_owner": 0, "missing_status": 0, "missing_history": 0},
        "freshness": {
            "active_documents": 22,
            "evaluated_documents": 22,
            "stale_answer_violations": 0,
            "revoked_answer_violations": 0,
            "connector_failure_answer_violations": 0,
        },
        "trace_privacy": {"total_traces": 10, "sampled_traces": 10, "sensitive_findings": 0, "unauthorized_raw_content": 0},
        "backup_restore": {
            "backup_digest": "c" * 64,
            "restore_smoke_status": "PASS",
            "rollback_status": "PASS",
            "rto_seconds": 120,
            "target_rto_seconds": 300,
        },
    }


def test_operations_gate_requires_complete_operator_evidence():
    evidence = _evidence()
    assert validate_operator_evidence(
        evidence,
        image_digest=evidence["image_digest"],
        revision_id="revision-1",
        manifest_hash="manifest-1",
    ) == (True, [])


def test_operations_gate_rejects_privacy_and_restore_failures():
    evidence = _evidence()
    evidence["trace_privacy"]["sensitive_findings"] = 1
    evidence["backup_restore"]["rto_seconds"] = 600
    passed, reasons = validate_operator_evidence(
        evidence,
        image_digest=evidence["image_digest"],
        revision_id="revision-1",
        manifest_hash="manifest-1",
    )
    assert passed is False
    assert "trace_privacy_violation" in reasons
    assert "recovery_rto_missed" in reasons
