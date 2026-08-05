"""問答 Langfuse trace 輔助（CG-OBS）— 串流／非串流共用。

將 retrieval、generation、source_verification 串成單一 trace，
便於事後定位「哪個租戶、哪次問答、哪段檢索、溯源是否通過」。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class ChatTraceHandle:
    """Langfuse trace 句柄；lf_trace 為 None 時所有方法為 no-op。"""

    lf_trace: Any = None

    @property
    def trace_id(self) -> Optional[str]:
        return getattr(self.lf_trace, "id", None) if self.lf_trace else None


def start_chat_trace(
    *,
    user_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    question: str,
    stream: bool = True,
) -> ChatTraceHandle:
    from app.services.langfuse_client import get_langfuse

    lf = get_langfuse()
    if not lf:
        return ChatTraceHandle()

    try:
        trace = lf.trace(
            name="rag_chat_stream" if stream else "rag_chat",
            user_id=str(user_id),
            metadata={
                "tenant_id": str(tenant_id),
                "conversation_id": str(conversation_id),
                "stream": stream,
            },
            input=question,
        )
        return ChatTraceHandle(lf_trace=trace)
    except Exception as exc:
        logger.warning("Langfuse trace 建立失敗（降級 no-op）: %s", exc)
        return ChatTraceHandle()


def record_retrieval_span(
    handle: ChatTraceHandle,
    *,
    effective_question: str,
    ctx: Dict[str, Any],
    top_k: int,
) -> None:
    if not handle.lf_trace:
        return

    sources = ctx.get("sources") or []
    chunk_scores = [
        s.get("score", 0) for s in sources if isinstance(s, dict) and s.get("score") is not None
    ]
    avg_score = round(sum(chunk_scores) / len(chunk_scores), 4) if chunk_scores else 0.0
    retrieval = ctx.get("retrieval") or {}

    try:
        handle.lf_trace.span(
            name="retrieval",
            input=effective_question,
            output={
                "num_sources": len(sources),
                "avg_chunk_score": avg_score,
                "has_policy": ctx.get("has_policy", False),
                "request_id": ctx.get("request_id"),
                "degraded": retrieval.get("degraded", False),
                "providers_called": retrieval.get("providers_called"),
            },
            metadata={
                "top_k": top_k,
                "chunk_scores": chunk_scores[:10],
            },
        )
    except Exception as exc:
        logger.warning("Langfuse retrieval span 失敗: %s", exc)


def record_source_verification_span(
    handle: ChatTraceHandle,
    ctx: Dict[str, Any],
) -> None:
    """記錄 source_verification 稽核結果（shadow／enforce 模式）。"""
    if not handle.lf_trace:
        return

    sv = ctx.get("source_verification")
    if not sv:
        return

    verified = bool(sv.get("verified"))
    try:
        from app.observability.business_metrics import record_source_verify_result

        mode = str(sv.get("mode") or "unknown")
        record_source_verify_result(verified=verified, mode=mode)
    except Exception:
        pass

    try:
        handle.lf_trace.span(
            name="source_verification",
            input={"mode": sv.get("mode")},
            output={
                "verified": verified,
                "total_claims": sv.get("total_claims", 0),
                "unsupported_count": len(sv.get("unsupported_claims") or []),
                "reason": sv.get("reason"),
            },
            metadata={
                "unsupported_claims": (sv.get("unsupported_claims") or [])[:5],
            },
        )
    except Exception as exc:
        logger.warning("Langfuse source_verification span 失敗: %s", exc)


def record_generation(
    handle: ChatTraceHandle,
    *,
    model: str,
    question: str,
    answer: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
) -> None:
    if not handle.lf_trace:
        return

    preview = answer[:500] if answer else ""
    try:
        handle.lf_trace.generation(
            name="llm_generation",
            model=model,
            input=question,
            output=preview,
            usage={"input": input_tokens, "output": output_tokens},
            metadata={"latency_ms": latency_ms},
        )
        handle.lf_trace.update(output=preview)
    except Exception as exc:
        logger.warning("Langfuse generation 記錄失敗: %s", exc)


def finalize_chat_trace(handle: ChatTraceHandle) -> None:
    if not handle.lf_trace:
        return
    try:
        from app.services.langfuse_client import get_langfuse

        lf = get_langfuse()
        if lf:
            lf.flush()
    except Exception as exc:
        logger.warning("Langfuse flush 失敗: %s", exc)
