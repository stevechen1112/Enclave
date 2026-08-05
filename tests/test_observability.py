"""CG-OBS 測試：Sentry／Langfuse 客戶端、chat trace 輔助、業務 Prometheus 指標。"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services.langfuse_client import get_langfuse, reset_langfuse_for_testing


class TestSentryInit:
    def test_no_dsn_is_noop(self, monkeypatch):
        from app.observability import sentry as sentry_mod

        sentry_mod._initialized_services.clear()
        monkeypatch.setattr("app.config.settings.SENTRY_DSN", "")
        sentry_mod.init_sentry("test-api")
        assert "test-api" not in sentry_mod._initialized_services


class TestLangfuseClient:
    def setup_method(self):
        reset_langfuse_for_testing()

    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.LANGFUSE_ENABLED", False)
        assert get_langfuse() is None

    def test_missing_keys_returns_none(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.LANGFUSE_ENABLED", True)
        monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "")
        monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "")
        assert get_langfuse() is None

    def test_init_success(self, monkeypatch):
        monkeypatch.setattr("app.services.langfuse_client._HAS_LANGFUSE", True)
        monkeypatch.setattr("app.config.settings.LANGFUSE_ENABLED", True)
        monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setattr("app.config.settings.LANGFUSE_HOST", "https://lf.example")

        mock_lf = MagicMock()
        with patch("app.services.langfuse_client.Langfuse", return_value=mock_lf):
            reset_langfuse_for_testing()
            assert get_langfuse() is mock_lf


class TestChatObservability:
    def test_noop_when_langfuse_disabled(self, monkeypatch):
        from app.services import chat_observability as co

        monkeypatch.setattr("app.services.langfuse_client.get_langfuse", lambda: None)
        handle = co.start_chat_trace(
            user_id=uuid4(),
            tenant_id=uuid4(),
            conversation_id=uuid4(),
            question="test",
        )
        assert handle.trace_id is None
        co.record_retrieval_span(handle, effective_question="q", ctx={"sources": []}, top_k=5)
        co.record_source_verification_span(handle, {"source_verification": {"verified": False, "mode": "shadow"}})
        co.record_generation(handle, model="m", question="q", answer="a", input_tokens=1, output_tokens=2, latency_ms=10)
        co.finalize_chat_trace(handle)  # no raise

    def test_trace_records_spans(self, monkeypatch):
        from app.services import chat_observability as co

        mock_trace = MagicMock()
        mock_trace.id = "trace-123"
        mock_lf = MagicMock()
        mock_lf.trace.return_value = mock_trace
        monkeypatch.setattr("app.services.langfuse_client.get_langfuse", lambda: mock_lf)

        handle = co.start_chat_trace(
            user_id=uuid4(),
            tenant_id=uuid4(),
            conversation_id=uuid4(),
            question="問題",
        )
        assert handle.trace_id == "trace-123"
        co.record_retrieval_span(
            handle,
            effective_question="問題",
            ctx={"sources": [{"score": 0.9}], "has_policy": True, "request_id": "r1"},
            top_k=5,
        )
        mock_trace.span.assert_called_once()
        co.record_source_verification_span(
            handle,
            {"source_verification": {"verified": True, "mode": "shadow", "total_claims": 2, "unsupported_claims": []}},
        )
        assert mock_trace.span.call_count == 2
        co.record_generation(
            handle, model="gpt-test", question="q", answer="ans", input_tokens=10, output_tokens=20, latency_ms=100
        )
        mock_trace.generation.assert_called_once()
        co.finalize_chat_trace(handle)
        mock_lf.flush.assert_called_once()


class TestBusinessMetrics:
    def test_record_quota_exceeded_no_crash(self):
        from app.observability.business_metrics import record_quota_exceeded

        record_quota_exceeded("query")

    def test_record_source_verify_no_crash(self):
        from app.observability.business_metrics import record_source_verify_result

        record_source_verify_result(verified=False, mode="enforce")
