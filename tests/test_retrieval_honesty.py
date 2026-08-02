"""UX-3: retrieval honesty — degraded flag + source revision fields."""
from __future__ import annotations

from app.services.chat_orchestrator import ChatOrchestrator


def test_build_context_marks_canonical_fallback_degraded():
    orch = ChatOrchestrator.__new__(ChatOrchestrator)
    ctx = orch._build_context(
        question="請假規定？",
        company_policy={
            "status": "success",
            "results": [
                {
                    "id": "c1",
                    "content": "年假依勞基法辦理",
                    "filename": "leave.pdf",
                    "score": 0.9,
                    "document_id": "doc-1",
                    "document_revision": 3,
                    "provider": "canonical",
                    "chunk_index": 0,
                }
            ],
            "retrieval_mode": "canonical_fallback",
            "degraded": True,
        },
        request_id="req-test-1",
    )
    assert ctx["retrieval"]["degraded"] is True
    assert ctx["retrieval"]["mode"] == "canonical_fallback"
    assert ctx["retrieval"]["request_id"] == "req-test-1"
    assert "本機主索引" in ctx["retrieval"]["label"]
    assert ctx["sources"]
    src = ctx["sources"][0]
    assert src.get("document_id") == "doc-1"
    assert src.get("document_revision") == 3
    assert src.get("provider") == "canonical"


def test_build_context_gateway_not_degraded():
    orch = ChatOrchestrator.__new__(ChatOrchestrator)
    ctx = orch._build_context(
        question="q",
        company_policy={
            "status": "success",
            "results": [
                {
                    "content": "ok",
                    "filename": "a.pdf",
                    "score": 0.8,
                    "document_revision": 1,
                }
            ],
            "retrieval_mode": "gateway",
            "degraded": False,
        },
        request_id="req-2",
    )
    assert ctx["retrieval"]["degraded"] is False
    assert ctx["retrieval"]["mode"] == "gateway"
