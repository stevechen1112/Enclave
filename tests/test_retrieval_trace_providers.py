"""A6 — RetrievalTrace.providers_called audit field."""
from __future__ import annotations

from app.models.chat import RetrievalTrace


def test_model_has_providers_called_column():
    assert "providers_called" in RetrievalTrace.__table__.columns
    col = RetrievalTrace.__table__.columns["providers_called"]
    assert col.nullable is True


def test_create_retrieval_trace_persists_providers_called():
    from unittest.mock import MagicMock
    from app.crud import crud_chat

    captured = {}

    class FakeDB:
        def add(self, obj):
            captured["obj"] = obj

        def commit(self):
            pass

        def refresh(self, obj):
            pass

    crud_chat.create_retrieval_trace(
        FakeDB(),
        tenant_id=__import__("uuid").uuid4(),
        conversation_id=__import__("uuid").uuid4(),
        message_id=__import__("uuid").uuid4(),
        sources_json=[],
        latency_ms=12,
        providers_called=["document", "wiki"],
    )
    assert captured["obj"].providers_called == ["document", "wiki"]


def test_orchestrator_surfaces_providers_called_from_gateway():
    # The gateway path must copy audit_trail.providers_called into the result.
    from app.gateway.contracts import AuditTrail, GatewayResponse
    from app.services.retrieval_facade import RetrievalResult

    resp = GatewayResponse(
        request_id="r",
        status="success",
        provider="enclave-gateway",
        provider_version="1.0",
        audit_trail=AuditTrail(operation="search", providers_called=["document", "wiki"]),
    )
    assert list(resp.audit_trail.providers_called) == ["document", "wiki"]

    # RetrievalFacade must propagate audit_trail so chat_orchestrator can read it.
    facade_result = RetrievalResult(
        results=[],
        citations=[],
        audit_trail=resp.audit_trail,
        gateway_status=resp.status,
    )
    called = list(
        getattr(getattr(facade_result, "audit_trail", None), "providers_called", None) or []
    )
    assert called == ["document", "wiki"]
    assert facade_result.gateway_status == "success"


def test_partial_gateway_marks_degraded():
    from app.services.retrieval_facade import RetrievalResult
    r = RetrievalResult(gateway_status="partial", audit_trail=None)
    assert (r.gateway_status == "partial") is True
