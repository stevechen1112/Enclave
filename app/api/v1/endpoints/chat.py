from typing import Any, List, Optional
from uuid import UUID
import json
import logging
import time

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session

from app.api import deps
from app.crud import crud_chat
from app.models.user import User
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    Conversation,
    ConversationCreate,
    Message,
    FeedbackCreate,
    FeedbackResponse,
    FeedbackStats,
)
from app.services.chat_orchestrator import ChatOrchestrator
from app.api.v1.endpoints.audit import log_usage
from app.crud import crud_tenant  # top-level import — avoid repeated in-function imports

router = APIRouter()


def _raise_quota_exceeded(reservation: dict) -> None:
    axis = reservation.get("axis", "query")
    try:
        from app.observability.business_metrics import record_quota_exceeded

        record_quota_exceeded(str(axis))
    except Exception:
        pass
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": "quota_exceeded",
            "axis": reservation.get("axis", "query"),
            "message": reservation.get("message", "配額已超過"),
            "current": reservation.get("current"),
            "limit": reservation.get("limit"),
        },
    )


def _estimate_usage_cost(
    input_tokens: int,
    output_tokens: int,
    pinecone_queries: int = 0,
    embedding_calls: int = 0,
) -> float:
    return (
        input_tokens * 0.00001
        + output_tokens * 0.00003
        + pinecone_queries * 0.0001
        + embedding_calls * 0.0001
    )


def _finalize_chat_usage(
    db: Session,
    usage_record_id: UUID,
    *,
    input_tokens: int,
    output_tokens: int,
    pinecone_queries: int = 0,
    embedding_calls: int = 0,
) -> None:
    from app.crud import crud_audit

    crud_audit.update_usage_record(
        db,
        usage_record_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        pinecone_queries=pinecone_queries,
        embedding_calls=embedding_calls,
        estimated_cost=_estimate_usage_cost(
            input_tokens, output_tokens, pinecone_queries, embedding_calls
        ),
    )

# Module-level singleton: ChatOrchestrator initialises LLM/embedding clients once
# at import time rather than on every request (avoids repeated OpenAI client construction).
_orchestrator: Optional[ChatOrchestrator] = None


def _get_orchestrator() -> ChatOrchestrator:
    """Return the module-level ChatOrchestrator singleton, creating it on first call."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ChatOrchestrator()
    return _orchestrator


def _resolve_conversation(db: Session, request: ChatRequest, current_user: User):
    """驗證或略過 conversation_id；失敗時 raise，不消耗配額。"""
    conversation_id = request.conversation_id
    if not conversation_id:
        return None
    conversation = crud_chat.get_conversation(db, conversation_id=conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="對話不存在")
    if conversation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="無權訪問此對話")
    return conversation


# ──────────── T7-1: SSE 串流端點 ────────────

@router.post("/chat/stream")
async def chat_stream(
    *,
    db: Session = Depends(deps.get_db),
    request: ChatRequest,
    current_user: User = Depends(deps.get_current_verified_user),
) -> StreamingResponse:
    """
    串流式聊天（SSE）— T7-1

    回傳 text/event-stream，事件格式：
    - {type: 'status', content: '...'} — 狀態提示
    - {type: 'sources', sources: [...]}  — 來源引用
    - {type: 'token', content: '...'}    — LLM 逐字 token
    - {type: 'suggestions', items: [...]} — 建議追問（T7-6）
    - {type: 'done', message_id: '...', conversation_id: '...'} — 完成
    """
    if not request.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="問題不能為空",
        )

    conversation = _resolve_conversation(db, request, current_user)

    # 0. 原子性預留查詢配額（對話歸屬已驗證）
    reservation = crud_tenant.reserve_chat_quota(
        db, current_user.tenant_id, current_user.id
    )
    if not reservation.get("allowed", True):
        _raise_quota_exceeded(reservation)
    usage_record_id = reservation["usage_record_id"]

    # 1. 獲取或建立對話
    if conversation is None:
        conversation = crud_chat.create_conversation(
            db,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            title=request.question[:50],
        )

    # 2. 儲存用戶訊息
    user_message = crud_chat.create_message(
        db,
        conversation_id=conversation.id,
        role="user",
        content=request.question,
    )

    # 3. 取得歷史對話（T7-2 多輪）
    history = _get_history(db, conversation.id, exclude_message_id=user_message.id)

    orchestrator = _get_orchestrator()

    # SSE generator 在 endpoint return 後才執行；get_current_user 的 Session 會先關閉，
    # 導致 current_user 變成 DetachedInstance。必須在此先物化 AuthZ 與純量 ID。
    from app.core.authorization import AuthorizationContext
    authz = AuthorizationContext.from_user(current_user)
    tenant_id = current_user.tenant_id
    user_id = current_user.id
    conversation_id_val = conversation.id

    # 明確指定 module_key 時的授權（必須在 SSE 開始前 403）
    _assert_chat_module_access(db, current_user, getattr(request, "module_key", None))
    from app.services.job_context import build_effective_job_context

    _job_role_keys = list(build_effective_job_context(db, current_user).active_job_role_keys)

    async def event_generator():
        start_time = time.time()
        full_answer = ""
        from app.db.session import SessionLocal
        from app.services.chat_observability import (
            finalize_chat_trace,
            record_generation,
            record_retrieval_span,
            record_source_verification_span,
            start_chat_trace,
        )

        # SSE generator 在 endpoint return 後才執行，request-scoped db 已關閉；
        # 所有 DB 操作必須使用這裡新開的 session。
        stream_db = SessionLocal()

        lf_handle = start_chat_trace(
            user_id=user_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id_val,
            question=request.question,
            stream=True,
        )

        try:
            # Phase 1: 狀態 — 正在檢索
            yield _sse({"type": "status", "content": "正在搜尋可存取知識…"})

            # P1-4：職能模組 Router + SceneContext → 檢索 filter
            from app.services.scene_scope import scene_question_hint, scene_to_filter_dict

            module_key = getattr(request, "module_key", None)
            module_scope, module_label = _module_retrieval_scope(
                stream_db, authz, module_key, job_role_keys=_job_role_keys
            )
            if module_label:
                yield _sse({"type": "status", "content": f"已切換至 {module_label} 模組"})

            scene_filter = scene_to_filter_dict(getattr(request, "scene_context", None))
            filter_dict = {**module_scope, **scene_filter}

            # T7-2: 查詢改寫
            effective_question = request.question
            if history:
                effective_question = await orchestrator.contextualize_query(
                    request.question, history
                )
            hint = scene_question_hint(getattr(request, "scene_context", None))
            if hint and hint not in effective_question:
                effective_question = f"{effective_question}\n{hint}"

            # Phase 2: 檢索（Phase 0：傳遞 AuthorizationContext）
            ctx = await orchestrator.retrieve_context(
                tenant_id=tenant_id,
                question=effective_question,
                top_k=request.top_k,
                authz=authz,
                db=stream_db,
                filter_dict=filter_dict or None,
            )

            # Retrieval honesty (degraded / request_id) before sources
            retrieval = ctx.get("retrieval") or {
                "mode": "canonical",
                "degraded": False,
                "request_id": ctx.get("request_id"),
            }
            yield _sse({"type": "retrieval", "retrieval": retrieval})

            # 立即推送來源（含 document_revision 等欄位）
            yield _sse({"type": "sources", "sources": ctx["sources"]})

            record_retrieval_span(
                lf_handle,
                effective_question=effective_question,
                ctx=ctx,
                top_k=request.top_k,
            )

            # Phase 3: 串流生成
            yield _sse({"type": "status", "content": "正在整理證據並產生回答…"})

            async for chunk in orchestrator.stream_answer(
                question=request.question,
                context=ctx,
                history=history,
                include_followup=True,
            ):
                full_answer += chunk
                yield _sse({"type": "token", "content": chunk})

            record_source_verification_span(lf_handle, ctx)

            # T7-6: 解析建議問題
            suggestions = _parse_suggestions(full_answer)
            if suggestions:
                yield _sse({"type": "suggestions", "items": suggestions})

            # Phase 4: 儲存 assistant 訊息
            # 清理 answer（移除 [建議問題] 區塊）
            clean_answer = _strip_suggestions(full_answer)
            assistant_message = crud_chat.create_message(
                stream_db,
                conversation_id=conversation_id_val,
                role="assistant",
                content=clean_answer,
            )

            # 儲存 retrieval trace
            crud_chat.create_retrieval_trace(
                stream_db,
                tenant_id=tenant_id,
                conversation_id=conversation_id_val,
                message_id=assistant_message.id,
                sources_json=ctx["sources"],
                latency_ms=int((time.time() - start_time) * 1000),
                providers_called=(ctx.get("retrieval") or {}).get("providers_called"),
            )

            # 記錄用量
            # 輸入估算：問題 + 系統 prompt（~600 tokens） + context（從 context_parts 粗估）
            context_text_len = sum(len(p) for p in ctx.get("context_parts", []))
            SYSTEM_PROMPT_TOKENS = 600
            input_tokens = SYSTEM_PROMPT_TOKENS + len(request.question) // 2 + context_text_len // 2
            output_tokens = len(clean_answer) // 2
            if ctx.get("labor_law_raw") and ctx["labor_law_raw"].get("usage"):
                usage = ctx["labor_law_raw"]["usage"]
                input_tokens = usage.get("input_tokens", input_tokens)
                output_tokens = usage.get("output_tokens", output_tokens)

            _finalize_chat_usage(
                stream_db,
                usage_record_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                pinecone_queries=1 if ctx["has_policy"] else 0,
            )

            record_generation(
                lf_handle,
                model=orchestrator._llm_model,
                question=request.question,
                answer=clean_answer,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=int((time.time() - start_time) * 1000),
            )
            finalize_chat_trace(lf_handle)

            yield _sse({
                "type": "done",
                "message_id": str(assistant_message.id),
                "conversation_id": str(conversation_id_val),
            })

        except Exception as e:
            logger.exception("chat_stream event_generator 錯誤: %s", e)
            finalize_chat_trace(lf_handle)
            yield _sse({"type": "error", "content": f"處理失敗：{str(e)}"})
        finally:
            stream_db.close()


    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_generator(), media_type="text/event-stream", headers=headers
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    *,
    db: Session = Depends(deps.get_db),
    request: ChatRequest,
    current_user: User = Depends(deps.get_current_verified_user),
) -> Any:
    """
    發送聊天訊息（非串流，向下相容）
    - 並行查詢公司內規和勞資法
    - 合併結果並返回
    - 儲存對話歷史
    - 支援多輪對話 (T7-2)
    """
    if not request.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="問題不能為空"
        )

    conversation = _resolve_conversation(db, request, current_user)

    # 0. 原子性預留查詢配額（對話歸屬已驗證）
    reservation = crud_tenant.reserve_chat_quota(
        db, current_user.tenant_id, current_user.id
    )
    if not reservation.get("allowed", True):
        _raise_quota_exceeded(reservation)
    usage_record_id = reservation["usage_record_id"]

    # 1. 獲取或建立對話
    if conversation is None:
        conversation = crud_chat.create_conversation(
            db,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            title=request.question[:50]  # 使用問題前 50 字作為標題
        )
    
    # 2. 儲存用戶訊息
    user_message = crud_chat.create_message(
        db,
        conversation_id=conversation.id,
        role="user",
        content=request.question
    )
    
    # 3. 取得歷史對話（T7-2）
    history = _get_history(db, conversation.id, exclude_message_id=user_message.id)

    # 4. 使用協調器處理查詢（Phase 0: 傳遞 ACL）
    orchestrator = _get_orchestrator()
    from app.core.authorization import AuthorizationContext
    from app.services.chat_observability import (
        finalize_chat_trace,
        record_generation,
        record_retrieval_span,
        start_chat_trace,
    )

    authz = AuthorizationContext.from_user(current_user)
    _assert_chat_module_access(db, current_user, getattr(request, "module_key", None))
    from app.services.job_context import build_effective_job_context

    _job_role_keys = list(build_effective_job_context(db, current_user).active_job_role_keys)
    lf_handle = start_chat_trace(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        conversation_id=conversation.id,
        question=request.question,
        stream=False,
    )
    query_start = time.time()

    # P1-4：職能模組 Router + SceneContext → 檢索 filter（與串流路徑一致）
    from app.services.scene_scope import scene_question_hint, scene_to_filter_dict

    module_scope, _ = _module_retrieval_scope(
        db, authz, getattr(request, "module_key", None), job_role_keys=_job_role_keys
    )
    scene_ctx = getattr(request, "scene_context", None)
    filter_dict = {**module_scope, **scene_to_filter_dict(scene_ctx)}

    result = await orchestrator.process_query(
        tenant_id=current_user.tenant_id,
        question=request.question,
        top_k=request.top_k,
        history=history,
        authz=authz,
        db=db,
        filter_dict=filter_dict or None,
        question_hint=scene_question_hint(scene_ctx),
    )

    record_retrieval_span(
        lf_handle,
        effective_question=request.question,
        ctx={
            "sources": result.get("sources") or [],
            "has_policy": result.get("company_policy") is not None,
            "request_id": result.get("request_id"),
            "retrieval": result.get("retrieval") or {},
        },
        top_k=request.top_k,
    )
    
    # 5. 儲存助手回應
    assistant_message = crud_chat.create_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content=result["answer"]
    )

    # 5b. 持久化證據（與 SSE 路徑對齊；否則歷史對話右側證據欄永遠空白）
    crud_chat.create_retrieval_trace(
        db,
        tenant_id=current_user.tenant_id,
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        sources_json=result.get("sources") or [],
        providers_called=(result.get("retrieval") or {}).get("providers_called"),
    )
    
    # 6. 記錄用量
    # 輸入估算：系統 prompt（~600 tokens） + 問題 + context
    context_text_len = sum(
        len(p) for p in (result.get("company_policy") and
            [result["company_policy"].get("content", "")] or [])
    )
    SYSTEM_PROMPT_TOKENS = 600
    input_tokens = SYSTEM_PROMPT_TOKENS + len(request.question) // 2 + context_text_len // 2
    output_tokens = len(result["answer"]) // 2
    pinecone_queries = 1 if result.get("company_policy") else 0
    
    # 從 labor_law 獲取實際 token 數（如果有）
    if result.get("labor_law") and result["labor_law"].get("usage"):
        usage = result["labor_law"]["usage"]
        input_tokens = usage.get("input_tokens", input_tokens)
        output_tokens = usage.get("output_tokens", output_tokens)
    
    _finalize_chat_usage(
        db,
        usage_record_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        pinecone_queries=pinecone_queries,
    )

    record_generation(
        lf_handle,
        model=orchestrator._llm_model,
        question=request.question,
        answer=result["answer"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=int((time.time() - query_start) * 1000),
    )
    finalize_chat_trace(lf_handle)

    # 7. 返回結果
    return ChatResponse(
        request_id=result["request_id"],
        question=result["question"],
        answer=result["answer"],
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        company_policy=result.get("company_policy"),
        labor_law=result.get("labor_law"),
        sources=result["sources"],
        notes=result["notes"],
        disclaimer=result["disclaimer"]
    )


@router.get("/conversations", response_model=List[Conversation])
def list_conversations(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """獲取當前用戶的對話列表"""
    conversations = crud_chat.get_user_conversations(
        db,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        skip=skip,
        limit=limit
    )
    return conversations


# ──────────── T7-13: 對話搜尋 (must be BEFORE /conversations/{conversation_id}) ────────────

@router.get("/conversations/search")
async def search_conversations(
    *,
    db: Session = Depends(deps.get_db),
    q: str = Query(..., min_length=1),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """搜尋對話內容"""
    results = crud_chat.search_messages(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        query=q,
        limit=20,
    )
    return results


@router.get("/conversations/{conversation_id}", response_model=Conversation)
def get_conversation(
    *,
    db: Session = Depends(deps.get_db),
    conversation_id: UUID,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """獲取特定對話"""
    conversation = crud_chat.get_conversation(db, conversation_id=conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="對話不存在"
        )
    if conversation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="無權訪問此對話"
        )
    return conversation


@router.get("/conversations/{conversation_id}/messages", response_model=List[Message])
def get_conversation_messages(
    *,
    db: Session = Depends(deps.get_db),
    conversation_id: UUID,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """獲取對話的訊息歷史"""
    conversation = crud_chat.get_conversation(db, conversation_id=conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="對話不存在"
        )
    if conversation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="無權訪問此對話"
        )
    
    messages = crud_chat.get_conversation_messages(
        db, conversation_id=conversation_id, skip=skip, limit=limit
    )
    out: list[Message] = []
    for m in messages:
        raw_sources = None
        trace = getattr(m, "retrieval_trace", None)
        if trace is not None and trace.sources_json is not None:
            sj = trace.sources_json
            raw_sources = sj if isinstance(sj, list) else []
        out.append(
            Message.model_validate(
                {
                    "id": m.id,
                    "conversation_id": m.conversation_id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at,
                    "sources": raw_sources,
                }
            )
        )
    return out


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    *,
    db: Session = Depends(deps.get_db),
    conversation_id: UUID,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """刪除對話"""
    conversation = crud_chat.get_conversation(db, conversation_id=conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="對話不存在"
        )
    if conversation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="無權刪除此對話"
        )
    
    crud_chat.delete_conversation(db, conversation_id=conversation_id)
    return {"message": "對話已刪除", "conversation_id": str(conversation_id)}


# ──────────── T7-5: Feedback 回饋系統 ────────────

@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    *,
    db: Session = Depends(deps.get_db),
    feedback: FeedbackCreate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """提交聊天回饋（👍/👎）"""
    # 驗證 message 存在
    msg = crud_chat.get_message_by_id(db, message_id=feedback.message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="訊息不存在")

    result = crud_chat.upsert_feedback(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        message_id=feedback.message_id,
        rating=feedback.rating,
        category=feedback.category,
        comment=feedback.comment,
    )
    return result


@router.get("/feedback/stats", response_model=FeedbackStats)
async def feedback_stats(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """取得回饋統計（管理員）"""
    if current_user.role not in ("owner", "admin", "hr") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="僅管理員可查看回饋統計")
    stats = crud_chat.get_feedback_stats(db, tenant_id=current_user.tenant_id)
    return stats


# ──────────── T7-11: 對話匯出 ────────────

@router.get("/conversations/{conversation_id}/export")
async def export_conversation(
    *,
    db: Session = Depends(deps.get_db),
    conversation_id: UUID,
    format: str = Query("markdown", enum=["markdown"]),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """匯出對話為 Markdown"""
    conversation = crud_chat.get_conversation(db, conversation_id=conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="對話不存在")
    if conversation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="無權訪問此對話")

    messages = crud_chat.get_conversation_messages(db, conversation_id=conversation_id)

    lines = [f"# {conversation.title or '對話記錄'}\n"]
    lines.append(f"> 匯出時間：{time.strftime('%Y-%m-%d %H:%M')}\n\n---\n")
    for msg in messages:
        role_label = "👤 使用者" if msg.role == "user" else "🤖 AI 助理"
        lines.append(f"### {role_label}\n\n{msg.content}\n")

    content = "\n".join(lines)
    return Response(
        content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="conversation_{conversation_id}.md"'
        },
    )


# ──────────── T7-12: RAG 品質儀表板 ────────────

@router.get("/dashboard/rag")
async def rag_dashboard(
    *,
    db: Session = Depends(deps.get_db),
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """取得 RAG 品質儀表板數據（owner / admin / hr）"""
    if current_user.role not in ("owner", "admin", "hr"):
        raise HTTPException(status_code=403, detail="僅管理員可查看")
    return crud_chat.get_rag_dashboard(db, tenant_id=current_user.tenant_id, days=days)


# ──────────── 內部 helper ────────────

def _assert_chat_module_access(db: Session, current_user: User, module_key: Optional[str]) -> None:
    """明確指定 module_key 時的直接 URL 授權（/ask?module= 不只隱藏選單）。

    必須在 SSE 回應開始前呼叫，才能正確回 403。
    """
    if not module_key:
        return
    from app.config import settings

    if not settings.MODULE_ROUTER_ENABLED:
        return
    from app.services.job_context import ModuleAccessDenied, assert_module_access

    try:
        assert_module_access(db, current_user, module_key)
    except ModuleAccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))


def _module_retrieval_scope(
    db: Session, authz: Any, module_key: Optional[str],
    job_role_keys: Optional[List[str]] = None,
) -> tuple:
    """僅在請求明確帶 module_key 時才套用該模組的檢索範圍。

    回傳 (scope_dict, module_label)；未指定或模組不可用時回傳 ({}, None)，
    避免一般問答被預設模組的 knowledge_scope_policy 限縮。
    """
    if not module_key:
        return {}, None
    from app.config import settings

    if not settings.MODULE_ROUTER_ENABLED:
        return {}, None
    from app.services.module_router import get_module_router

    module_router = get_module_router(db=db)
    for m in module_router.get_available_modules(authz, job_role_keys=job_role_keys):
        name = getattr(m, "name", None) or (
            m.get("module_key") if isinstance(m, dict) else None
        )
        if name != module_key:
            continue
        label = getattr(m, "label", None) or (
            m.get("name") if isinstance(m, dict) else None
        ) or name
        return module_router.get_retrieval_scope(name, authz) or {}, label
    return {}, None


def _sse(data: dict) -> str:
    """格式化 SSE 事件。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_history(
    db: Session,
    conversation_id: UUID,
    exclude_message_id: UUID = None,
    max_turns: int = 5,
) -> List[dict]:
    """取得最近 N 輪歷史訊息（T7-2）。"""
    messages = crud_chat.get_conversation_messages(
        db, conversation_id=conversation_id, skip=0, limit=100
    )
    history = []
    for msg in messages:
        if exclude_message_id and msg.id == exclude_message_id:
            continue
        history.append({"role": msg.role, "content": msg.content})

    # 最多保留最近 max_turns * 2 條（user+assistant 為一輪）
    return history[-(max_turns * 2):]


def _parse_suggestions(text: str) -> List[str]:
    """解析 LLM 回答中的 [建議問題] 區塊（T7-6）。"""
    import re
    marker = "[建議問題]"
    idx = text.find(marker)
    if idx == -1:
        return []
    block = text[idx + len(marker):]
    suggestions = re.findall(r"\d+\.\s*(.+)", block)
    return [s.strip() for s in suggestions if s.strip()][:3]


def _strip_suggestions(text: str) -> str:
    """從 answer 中移除 [建議問題] 區塊。"""
    marker = "[建議問題]"
    idx = text.find(marker)
    if idx == -1:
        return text
    return text[:idx].rstrip()

