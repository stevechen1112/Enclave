"""
MKA P6 — 企業系統寫入護欄測試。
"""
import pytest
from unittest.mock import MagicMock

from app.services.write_guardrail import (
    WriteRequest, WriteRisk, WriteStatus,
    WriteGuardrail, get_write_guardrail,
)


class TestWriteRequest:
    def test_auto_generate_ids(self):
        req = WriteRequest(
            target_system="erp",
            operation="create",
            risk=WriteRisk.LOW_RISK_WRITE,
            payload={"item": "test"},
        )
        assert req.request_id != ""
        assert req.correlation_id != ""
        assert req.idempotency_key != ""
        assert req.payload_hash != ""

    def test_payload_hash_immutable(self):
        req1 = WriteRequest(payload={"a": 1, "b": 2})
        req2 = WriteRequest(payload={"b": 2, "a": 1})  # 順序不同
        assert req1.payload_hash == req2.payload_hash  # sort_keys 確保一致

    def test_to_dict(self):
        req = WriteRequest(
            target_system="erp",
            operation="update",
            risk=WriteRisk.LOW_RISK_WRITE,
            payload={"id": 1},
        )
        d = req.to_dict()
        assert d["target_system"] == "erp"
        assert d["risk"] == "low_risk_write"
        assert d["status"] == "pending"


class TestWriteGuardrail:
    def test_prohibited_rejected(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.PROHIBITED,
            payload={},
        )
        valid, reason = guardrail.validate(req)
        assert valid is False
        assert "prohibited" in reason.lower()

    def test_high_risk_without_approval_rejected(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.HIGH_RISK_WRITE,
            approval_required=True,
            approval_token="",
            payload={},
        )
        valid, reason = guardrail.validate(req)
        assert valid is False
        assert "approval" in reason.lower()

    def test_high_risk_with_approval_accepted(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.HIGH_RISK_WRITE,
            approval_required=True,
            approval_token="token-001",
            payload={},
        )
        valid, reason = guardrail.validate(req)
        assert valid is True

    def test_read_only_accepted(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.READ_ONLY,
            payload={},
        )
        valid, reason = guardrail.validate(req)
        assert valid is True

    def test_low_risk_accepted(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.LOW_RISK_WRITE,
            payload={},
        )
        valid, reason = guardrail.validate(req)
        assert valid is True

    def test_max_retries_limit(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.LOW_RISK_WRITE,
            max_retries=10,
            payload={},
        )
        valid, reason = guardrail.validate(req)
        assert valid is False
        assert "max_retries" in reason.lower()

    def test_execute_success(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.LOW_RISK_WRITE,
            payload={"item": "test"},
        )
        result = guardrail.execute(
            req,
            execute_fn=lambda p: {"id": 123},
        )
        assert result.status == WriteStatus.SUCCESS
        assert result.result == {"id": 123}

    def test_execute_retry_then_success(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.LOW_RISK_WRITE,
            max_retries=3,
            payload={},
        )
        # 前兩次失敗，第三次成功
        attempts = [0]
        def flaky_fn(p):
            if attempts[0] < 2:
                attempts[0] += 1
                raise Exception("transient error")
            return {"ok": True}

        result = guardrail.execute(req, execute_fn=flaky_fn)
        assert result.status == WriteStatus.SUCCESS
        assert result.retry_count == 2

    def test_execute_all_fail_with_rollback(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.LOW_RISK_WRITE,
            max_retries=1,
            payload={"id": 1},
        )
        rollback_called = [False]
        def always_fail(p):
            raise Exception("permanent error")
        def rollback(p, r):
            rollback_called[0] = True

        result = guardrail.execute(req, execute_fn=always_fail, rollback_fn=rollback)
        assert result.status == WriteStatus.ROLLED_BACK
        assert rollback_called[0] is True

    def test_execute_all_fail_without_rollback(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.LOW_RISK_WRITE,
            max_retries=1,
            payload={},
        )
        result = guardrail.execute(req, execute_fn=lambda p: (_ for _ in ()).throw(Exception("fail")))
        assert result.status == WriteStatus.FAILED

    def test_idempotent_skip(self):
        guardrail = WriteGuardrail()
        req1 = WriteRequest(
            risk=WriteRisk.LOW_RISK_WRITE,
            payload={"id": 1},
        )
        # 第一次執行
        guardrail.execute(req1, execute_fn=lambda p: {"ok": True})
        # 第二次相同 idempotency_key
        req2 = WriteRequest(
            risk=WriteRisk.LOW_RISK_WRITE,
            payload={"id": 1},
        )
        req2.idempotency_key = req1.idempotency_key
        result = guardrail.execute(req2, execute_fn=lambda p: {"ok": True})
        # 應該冪等跳過
        assert result.status == WriteStatus.SUCCESS

    def test_audit_log(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.LOW_RISK_WRITE,
            target_system="erp",
            payload={},
        )
        guardrail.execute(req, execute_fn=lambda p: {"ok": True})
        log = guardrail.get_audit_log(correlation_id=req.correlation_id)
        assert len(log) >= 2  # validated + success
        assert all(e["correlation_id"] == req.correlation_id for e in log)

    def test_fail_closed_on_validation_failure(self):
        guardrail = WriteGuardrail()
        req = WriteRequest(
            risk=WriteRisk.PROHIBITED,
            payload={},
        )
        result = guardrail.execute(req, execute_fn=lambda p: {"ok": True})
        assert result.status == WriteStatus.FAILED
        assert "prohibited" in result.error.lower()