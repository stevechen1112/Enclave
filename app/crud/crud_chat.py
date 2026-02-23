from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.chat import Conversation, Message, RetrievalTrace
from app.models.feedback import ChatFeedback


def get_conversation(db: Session, conversation_id: UUID) -> Optional[Conversation]:
    return db.query(Conversation).filter(Conversation.id == conversation_id).first()


def get_user_conversations(
    db: Session,
    user_id: UUID,
    tenant_id: UUID,
    skip: int = 0,
    limit: int = 100
) -> List[Conversation]:
    return db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.tenant_id == tenant_id
    ).order_by(Conversation.created_at.desc()).offset(skip).limit(limit).all()


def create_conversation(
    db: Session,
    *,
    user_id: UUID,
    tenant_id: UUID,
    title: str = "新對話"
) -> Conversation:
    db_obj = Conversation(
        user_id=user_id,
        tenant_id=tenant_id,
        title=title
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def create_message(
    db: Session,
    *,
    conversation_id: UUID,
    role: str,
    content: str
) -> Message:
    db_obj = Message(
        conversation_id=conversation_id,
        role=role,
        content=content
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def get_message_by_id(db: Session, message_id: UUID) -> Optional[Message]:
    """根據 ID 取得單一訊息。"""
    return db.query(Message).filter(Message.id == message_id).first()


def get_conversation_messages(
    db: Session,
    conversation_id: UUID,
    skip: int = 0,
    limit: int = 100
) -> List[Message]:
    return db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at).offset(skip).limit(limit).all()


def delete_conversation(db: Session, conversation_id: UUID) -> bool:
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv:
        # 刪除相關訊息
        db.query(Message).filter(Message.conversation_id == conversation_id).delete()
        db.delete(conv)
        db.commit()
        return True
    return False


# ──────────── T7-1: RetrievalTrace ────────────

def create_retrieval_trace(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    sources_json: Any = None,
    latency_ms: int = None,
) -> RetrievalTrace:
    """儲存檢索追蹤記錄（SSE 串流用）。"""
    db_obj = RetrievalTrace(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=message_id,
        sources_json=sources_json or {},
        latency_ms=latency_ms,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


# ──────────── T7-5: Feedback ────────────

def upsert_feedback(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    message_id: UUID,
    rating: int,
    category: str = None,
    comment: str = None,
) -> ChatFeedback:
    """新增或更新回饋（同一使用者同一訊息只能一筆）。"""
    existing = db.query(ChatFeedback).filter(
        ChatFeedback.user_id == user_id,
        ChatFeedback.message_id == message_id,
    ).first()

    if existing:
        existing.rating = rating
        existing.category = category
        existing.comment = comment
        db.commit()
        db.refresh(existing)
        return existing

    db_obj = ChatFeedback(
        tenant_id=tenant_id,
        user_id=user_id,
        message_id=message_id,
        rating=rating,
        category=category,
        comment=comment,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def get_feedback_stats(db: Session, tenant_id: UUID, since=None) -> Dict[str, Any]:
    """取得回饋統計。since 如提供則只統計該日期後的資料。"""
    q = db.query(func.count(ChatFeedback.id)).filter(
        ChatFeedback.tenant_id == tenant_id
    )
    if since:
        q = q.filter(ChatFeedback.created_at >= since)
    total = q.scalar() or 0

    q2 = db.query(func.count(ChatFeedback.id)).filter(
        ChatFeedback.tenant_id == tenant_id,
        ChatFeedback.rating == 2,
    )
    if since:
        q2 = q2.filter(ChatFeedback.created_at >= since)
    positive = q2.scalar() or 0

    negative = total - positive

    # 差評原因分佈
    cat_q = (
        db.query(ChatFeedback.category, func.count(ChatFeedback.id))
        .filter(
            ChatFeedback.tenant_id == tenant_id,
            ChatFeedback.rating == 1,
        )
    )
    if since:
        cat_q = cat_q.filter(ChatFeedback.created_at >= since)
    category_rows = cat_q.group_by(ChatFeedback.category).all()
    categories = [{"category": c or "other", "count": cnt} for c, cnt in category_rows]

    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "positive_rate": round(positive / total, 4) if total > 0 else 0.0,
        "categories": categories,
    }


# ──────────── T7-13: 對話搜尋 ────────────

def search_messages(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    query: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """搜尋使用者的對話訊息。"""
    results = (
        db.query(Message, Conversation)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
            Message.content.ilike(f"%{query}%"),
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "conversation_id": str(conv.id),
            "conversation_title": conv.title,
            "message_id": str(msg.id),
            "role": msg.role,
            "snippet": msg.content[:200],
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }
        for msg, conv in results
    ]


# ──────────── T7-12: RAG 品質儀表板 ────────────

def get_rag_dashboard(db: Session, tenant_id: UUID, days: int = 30) -> Dict[str, Any]:
    """取得 RAG 品質儀表板統計資料。"""
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(days=days)

    # 1. 對話總量
    total_conversations = db.query(func.count(Conversation.id)).filter(
        Conversation.tenant_id == tenant_id,
        Conversation.created_at >= since,
    ).scalar() or 0

    # 2. 訊息總量
    total_messages = (
        db.query(func.count(Message.id))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tenant_id,
            Message.created_at >= since,
        )
        .scalar()
        or 0
    )

    # 3. 平均每對話輪次
    avg_turns = round(total_messages / max(total_conversations, 1) / 2, 1)

    # 4. 平均回覆延遲 (ms)
    avg_latency = (
        db.query(func.avg(RetrievalTrace.latency_ms))
        .filter(
            RetrievalTrace.tenant_id == tenant_id,
            RetrievalTrace.created_at >= since,
        )
        .scalar()
    )
    avg_latency = round(avg_latency or 0)

    # 5. 每日對話數（for chart）
    from sqlalchemy import cast, Date

    daily_rows = (
        db.query(
            cast(Conversation.created_at, Date).label("date"),
            func.count(Conversation.id).label("count"),
        )
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.created_at >= since,
        )
        .group_by(cast(Conversation.created_at, Date))
        .order_by(cast(Conversation.created_at, Date))
        .all()
    )
    daily_conversations = [
        {"date": str(row.date), "count": row.count} for row in daily_rows
    ]

    # 6. 回饋統計（同步對齊 days 範圍）
    feedback = get_feedback_stats(db, tenant_id, since=since)

    # 7. 延遲分佈
    p50 = _percentile_latency(db, tenant_id, since, 0.50)
    p95 = _percentile_latency(db, tenant_id, since, 0.95)

    return {
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "avg_turns_per_conversation": avg_turns,
        "avg_latency_ms": avg_latency,
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "daily_conversations": daily_conversations,
        "feedback": feedback,
    }


def _percentile_latency(db: Session, tenant_id: UUID, since, percentile: float) -> int:
    """大致計算延遲百分位（簡易方式，非精確 percentile）。"""
    latencies = (
        db.query(RetrievalTrace.latency_ms)
        .filter(
            RetrievalTrace.tenant_id == tenant_id,
            RetrievalTrace.created_at >= since,
            RetrievalTrace.latency_ms.isnot(None),
        )
        .order_by(RetrievalTrace.latency_ms)
        .all()
    )
    if not latencies:
        return 0
    vals = [r[0] for r in latencies]
    idx = int(len(vals) * percentile)
    idx = min(idx, len(vals) - 1)
    return vals[idx]
