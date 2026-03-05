"""
Analytics response schemas — P10-5 問答日誌分析。

These models are returned by the analytics endpoints in
``app/api/v1/endpoints/analytics.py`` and are consumed by the
admin dashboard frontend.
"""
from typing import Optional

from pydantic import BaseModel


class QuerySummary(BaseModel):
    """Aggregate statistics for a given time window."""

    total_queries: int
    answered_queries: int
    unanswered_queries: int
    answer_rate_pct: float
    avg_latency_ms: Optional[float]
    period_days: int


class DailyQueryCount(BaseModel):
    """Per-day breakdown of query volume."""

    date: str          # ISO-8601 date string, e.g. "2024-05-01"
    total: int
    answered: int
    unanswered: int


class TopQuery(BaseModel):
    """A frequently-asked question with its occurrence count."""

    question: str      # Truncated to 200 chars
    count: int
    last_seen: str     # ISO-8601 datetime string


class UnansweredQuery(BaseModel):
    """A user question for which the knowledge base had no matching documents."""

    question: str           # Truncated to 200 chars
    asked_at: str           # ISO-8601 datetime string
    conversation_id: str
