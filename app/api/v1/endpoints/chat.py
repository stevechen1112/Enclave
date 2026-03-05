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

router = APIRouter()


# ──────────── T7-1: SSE 串流端點 ────────────

@router.post("/chat/stream")
async def chat_stream(
    *,
    db: Session = Depends(deps.get_db),
    request: ChatRequest,
    current_user: User = Depends(deps.get_current_active_user),
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

    # 1. 獲取或建立對話
    conversation_id = request.conversation_id
    if conversation_id:
        conversation = crud_chat.get_conversation(db, conversation_id=conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="對話不存在")
        if conversation.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="無權訪問此對話")
    else:
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

    orchestrator = ChatOrchestrator()

    async def event_generator():
        start_time = time.time()
        full_answer = ""

        try:
            # Phase 1: 狀態 — 正在檢索
            yield _sse({"type": "status", "content": "正在搜尋知識庫..."})

            # T7-2: 查詢改寫
            effective_question = request.question
            if history:
                effective_question = await orchestrator.contextualize_query(
                    request.question, history
                )

            # Phase 2: 檢索
            ctx = await orchestrator.retrieve_context(
                tenant_id=current_user.tenant_id,
                question=effective_question,
                top_k=request.top_k,
            )

            # 立即推送來源
            yield _sse({"type": "sources", "sources": ctx["sources"]})

            # Phase 3: 串流生成
            yield _sse({"type": "status", "content": "正在生成回答..."})

            async for chunk in orchestrator.stream_answer(
                question=request.question,
                context=ctx,
                history=history,
                include_followup=True,
            ):
                full_answer += chunk
                yield _sse({"type": "token", "content": chunk})

            # T7-6: 解析建議問題
            suggestions = _parse_suggestions(full_answer)
            if suggestions:
                yield _sse({"type": "suggestions", "items": suggestions})

            # Phase 4: 儲存 assistant 訊息
            # 清理 answer（移除 [建議問題] 區塊）
            clean_answer = _strip_suggestions(full_answer)
            assistant_message = crud_chat.create_message(
                db,
                conversation_id=conversation.id,
                role="assistant",
                content=clean_answer,
            )

            # 儲存 retrieval trace
            crud_chat.create_retrieval_trace(
                db,
                tenant_id=current_user.tenant_id,
                conversation_id=conversation.id,
                message_id=assistant_message.id,
                sources_json=ctx["sources"],
                latency_ms=int((time.time() - start_time) * 1000),
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

            log_usage(
                db,
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                action_type="chat_query",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                pinecone_queries=1 if ctx["has_policy"] else 0,
                embedding_calls=0,
                metadata={"conversation_id": str(conversation.id)},
            )

            yield _sse({
                "type": "done",
                "message_id": str(assistant_message.id),
                "conversation_id": str(conversation.id),
            })

        except Exception as e:
            logger.exception(f"chat_stream event_generator 錯誤: {e}")
            yield _sse({"type": "error", "content": f"處理失敗：{str(e)}"})


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
    current_user: User = Depends(deps.get_current_active_user),
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

    # 0. 查詢配額檢查
    from app.crud import crud_tenant
    quota = crud_tenant.check_quota(db, current_user.tenant_id, "query")
    if not quota.get("allowed", True):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "quota_exceeded",
                "message": quota.get("message", "查詢配額已超過"),
                "current": quota.get("current"),
                "limit": quota.get("limit"),
            },
        )

    # 1. 獲取或建立對話
    conversation_id = request.conversation_id
    if conversation_id:
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
    else:
        # 建立新對話
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

    # 4. 使用協調器處理查詢
    orchestrator = ChatOrchestrator()
    result = await orchestrator.process_query(
        tenant_id=current_user.tenant_id,
        question=request.question,
        top_k=request.top_k,
        history=history,
    )
    
    # 5. 儲存助手回應
    assistant_message = crud_chat.create_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content=result["answer"]
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
    
    log_usage(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action_type="chat_query",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        pinecone_queries=pinecone_queries,
        embedding_calls=0,
        metadata={"conversation_id": str(conversation.id)}
    )
    
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
    return messages


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


# ─────────────────────────────────────────────────────────────
# P10-5: 問答日誌分析端點
# ─────────────────────────────────────────────────────────────

from datetime import datetime, timedelta, UTC
from sqlalchemy import func as sqlfunc, cast, Date as SADate, text as sa_text, Text as SAText
from app.models.chat import Conversation, Message, RetrievalTrace
from pydantic import BaseModel as PydanticBase


class QuerySummary(PydanticBase):
    total_queries: int
    answered_queries: int
    unanswered_queries: int
    answer_rate_pct: float
    avg_latency_ms: Optional[float]
    period_days: int


class DailyQueryCount(PydanticBase):
    date: str
    total: int
    answered: int
    unanswered: int


class TopQuery(PydanticBase):
    question: str
    count: int
    last_seen: str


class UnansweredQuery(PydanticBase):
    question: str
    asked_at: str
    conversation_id: str


@router.get("/analytics/summary", response_model=QuerySummary, tags=["analytics"])
async def query_analytics_summary(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    days: int = Query(30, ge=1, le=365, description="統計天數"),
) -> QuerySummary:
    """
    P10-5 — 問答日誌摘要統計。

    回傳指定天數內的查詢總數、答覆率、平均延遲。
    """
    if current_user.role not in ("admin", "owner") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理員或擁有者權限")

    since = datetime.now(UTC) - timedelta(days=days)
    tid = current_user.tenant_id

    # 用戶訊息總數
    total = (
        db.query(sqlfunc.count(Message.id))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tid,
            Message.role == "user",
            Message.created_at >= since,
        )
        .scalar()
        or 0
    )

    # 有 sources 的回答數量（=已答覆）
    answered = (
        db.query(sqlfunc.count(RetrievalTrace.id))
        .join(Message, RetrievalTrace.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            RetrievalTrace.tenant_id == tid,
            Message.role == "user",
            Message.created_at >= since,
            RetrievalTrace.sources_json.isnot(None),
            cast(RetrievalTrace.sources_json, SAText).notin_(['{}', '[]', 'null']),
        )
        .scalar()
        or 0
    )

    # 平均延遲（assistant 訊息的 RetrievalTrace）
    avg_latency = (
        db.query(sqlfunc.avg(RetrievalTrace.latency_ms))
        .join(Message, RetrievalTrace.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            RetrievalTrace.tenant_id == tid,
            Message.created_at >= since,
            RetrievalTrace.latency_ms.isnot(None),
        )
        .scalar()
    )

    unanswered = max(0, total - answered)
    rate = round((answered / total * 100) if total > 0 else 0.0, 1)

    return QuerySummary(
        total_queries=total,
        answered_queries=answered,
        unanswered_queries=unanswered,
        answer_rate_pct=rate,
        avg_latency_ms=round(float(avg_latency), 1) if avg_latency else None,
        period_days=days,
    )


@router.get("/analytics/trend", response_model=List[DailyQueryCount], tags=["analytics"])
async def query_analytics_trend(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    days: int = Query(30, ge=1, le=90, description="統計天數"),
) -> List[DailyQueryCount]:
    """
    P10-5 — 每日問答趨勢。

    回傳最近 N 天每日的查詢量（總計 / 已答覆 / 未答覆）。
    """
    if current_user.role not in ("admin", "owner") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理員或擁有者權限")

    since = datetime.now(UTC) - timedelta(days=days)
    tid = current_user.tenant_id

    # 每日總數
    daily_total = (
        db.query(
            sqlfunc.date_trunc("day", Message.created_at).label("day"),
            sqlfunc.count(Message.id).label("cnt"),
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tid,
            Message.role == "user",
            Message.created_at >= since,
        )
        .group_by(sqlfunc.date_trunc("day", Message.created_at))
        .all()
    )

    total_dict = {row.day.date(): row.cnt for row in daily_total}

    # 每日已答覆數（有 sources 的）
    daily_answered = (
        db.query(
            sqlfunc.date_trunc("day", Message.created_at).label("day"),
            sqlfunc.count(RetrievalTrace.id).label("cnt"),
        )
        .join(Message, RetrievalTrace.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            RetrievalTrace.tenant_id == tid,
            Message.role == "user",
            Message.created_at >= since,
        )
        .group_by(sqlfunc.date_trunc("day", Message.created_at))
        .all()
    )

    answered_dict = {row.day.date(): row.cnt for row in daily_answered}

    results = []
    import datetime as dt
    today = dt.date.today()
    for i in range(days - 1, -1, -1):
        d = today - dt.timedelta(days=i)
        tot = total_dict.get(d, 0)
        ans = answered_dict.get(d, 0)
        results.append(DailyQueryCount(
            date=d.isoformat(),
            total=tot,
            answered=min(ans, tot),
            unanswered=max(0, tot - ans),
        ))
    return results


@router.get("/analytics/top-queries", response_model=List[TopQuery], tags=["analytics"])
async def query_analytics_top(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
) -> List[TopQuery]:
    """
    P10-5 — 問答熱門問題（頻繁度排行）。

    回傳最常被問到的問題 Top N（完全相同的問題合併計次）。
    """
    if current_user.role not in ("admin", "owner") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理員或擁有者權限")

    since = datetime.now(UTC) - timedelta(days=days)
    tid = current_user.tenant_id

    rows = (
        db.query(
            Message.content.label("question"),
            sqlfunc.count(Message.id).label("cnt"),
            sqlfunc.max(Message.created_at).label("last_seen"),
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tid,
            Message.role == "user",
            Message.created_at >= since,
        )
        .group_by(Message.content)
        .order_by(sqlfunc.count(Message.id).desc())
        .limit(limit)
        .all()
    )

    return [
        TopQuery(
            question=r.question[:200],
            count=r.cnt,
            last_seen=r.last_seen.isoformat() if r.last_seen else "",
        )
        for r in rows
    ]


@router.get("/analytics/unanswered", response_model=List[UnansweredQuery], tags=["analytics"])
async def query_analytics_unanswered(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
) -> List[UnansweredQuery]:
    """
    P10-5 — 無法回答的問題清單。

    查詢知識庫未找到相關文件（sources 為空）的問題，
    供管理員判斷是否需要補充文件。
    """
    if current_user.role not in ("admin", "owner") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理員或擁有者權限")

    since = datetime.now(UTC) - timedelta(days=days)
    tid = current_user.tenant_id

    # 取得有 RetrievalTrace 且 sources 為空陣列的用戶訊息
    rows = (
        db.query(Message, RetrievalTrace)
        .join(RetrievalTrace, RetrievalTrace.message_id == Message.id, isouter=True)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tid,
            Message.role == "user",
            Message.created_at >= since,
            RetrievalTrace.id.isnot(None),
        )
        .order_by(Message.created_at.desc())
        .limit(limit * 3)  # 拉多一點再 Python 端過濾
        .all()
    )

    results = []
    for msg, trace in rows:
        sources = trace.sources_json if trace else []
        if not sources:
            results.append(UnansweredQuery(
                question=msg.content[:200],
                asked_at=msg.created_at.isoformat() if msg.created_at else "",
                conversation_id=str(msg.conversation_id),
            ))
        if len(results) >= limit:
            break

    return results


