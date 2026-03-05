"""
問答日誌分析端點 — P10-5。

Analytics endpoints are **read-only** and require the ``admin`` or ``owner``
role (or superuser).  They are mounted at ``/api/v1/chat/analytics/...`` via
the ``api_router`` in ``app/api/v1/api.py``.

Endpoints
---------
GET /analytics/summary       — aggregate stats for a time window
GET /analytics/trend         — per-day query volume breakdown
GET /analytics/top-queries   — most-frequently-asked questions
GET /analytics/unanswered    — questions with no matching documents
"""
import datetime as dt
from datetime import UTC, datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Text as SAText
from sqlalchemy import cast
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.api import deps
from app.models.chat import Conversation, Message, RetrievalTrace
from app.models.user import User
from app.schemas.analytics import (
    DailyQueryCount,
    QuerySummary,
    TopQuery,
    UnansweredQuery,
)

router = APIRouter()


def _require_analytics_access(current_user: User) -> None:
    """Raise HTTP 403 unless the caller is an admin, owner, or superuser."""
    if current_user.role not in ("admin", "owner") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理員或擁有者權限")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


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
    _require_analytics_access(current_user)

    since = datetime.now(UTC) - timedelta(days=days)
    tid = current_user.tenant_id

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

    answered = (
        db.query(sqlfunc.count(RetrievalTrace.id))
        .join(Message, RetrievalTrace.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            RetrievalTrace.tenant_id == tid,
            Message.role == "user",
            Message.created_at >= since,
            RetrievalTrace.sources_json.isnot(None),
            cast(RetrievalTrace.sources_json, SAText).notin_(["{}",  "[]", "null"]),
        )
        .scalar()
        or 0
    )

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


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


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
    _require_analytics_access(current_user)

    since = datetime.now(UTC) - timedelta(days=days)
    tid = current_user.tenant_id

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

    today = dt.date.today()
    results = []
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


# ---------------------------------------------------------------------------
# Top queries
# ---------------------------------------------------------------------------


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
    _require_analytics_access(current_user)

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


# ---------------------------------------------------------------------------
# Unanswered queries
# ---------------------------------------------------------------------------


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
    _require_analytics_access(current_user)

    since = datetime.now(UTC) - timedelta(days=days)
    tid = current_user.tenant_id

    # Pull extra rows then filter in Python to avoid a complex subquery
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
        .limit(limit * 3)
        .all()
    )

    results: List[UnansweredQuery] = []
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
