"""
Phase 13 — Pydantic schemas for Knowledge Base Maintenance
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


# ──────────────────────────────────────────────
# P13-1: Document Version
# ──────────────────────────────────────────────

class DocumentVersionOut(BaseModel):
    id: UUID
    document_id: UUID
    version: int
    filename: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    chunk_count: Optional[int] = None
    status: str
    change_note: Optional[str] = None
    uploaded_by: Optional[UUID] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentReuploadIn(BaseModel):
    """Body when re-uploading a new version of a document."""
    change_note: Optional[str] = None
    upload_mode: str = "immediate"  # immediate | review


# ──────────────────────────────────────────────
# P13-2: Version Diff
# ──────────────────────────────────────────────

class VersionDiffOut(BaseModel):
    document_id: UUID
    filename: str
    old_version: int
    new_version: int
    added_lines: int
    removed_lines: int
    diff_html: str  # unified diff rendered to HTML


# ──────────────────────────────────────────────
# P13-3: KB Health Dashboard
# ──────────────────────────────────────────────

class StaleDocumentOut(BaseModel):
    id: UUID
    filename: str
    file_type: Optional[str] = None
    status: str
    days_since_update: int
    department_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CategoryCoverage(BaseModel):
    category: str
    document_count: int
    indexed_count: int
    coverage_pct: float


class TopQueryOut(BaseModel):
    query_text: str
    count: int
    avg_confidence: Optional[float] = None


class KBHealthOut(BaseModel):
    """Aggregate knowledge-base health metrics."""
    total_documents: int
    completed_documents: int
    failed_documents: int
    stale_documents: int  # not updated beyond threshold
    stale_threshold_days: int
    index_coverage_pct: float
    avg_confidence_7d: Optional[float] = None
    stale_document_list: List[StaleDocumentOut] = []
    category_coverage: List[CategoryCoverage] = []
    top_queries: List[TopQueryOut] = []
    recent_gaps: int = 0


# ──────────────────────────────────────────────
# P13-4: Knowledge Gap
# ──────────────────────────────────────────────

class KnowledgeGapOut(BaseModel):
    id: UUID
    query_text: str
    confidence_score: float
    suggested_topic: Optional[str] = None
    category_name: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class KnowledgeGapResolveIn(BaseModel):
    document_id: Optional[UUID] = None
    resolve_note: Optional[str] = None


# ──────────────────────────────────────────────
# P13-5: Category / Taxonomy
# ──────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    parent_id: Optional[UUID] = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[UUID] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class CategoryOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    parent_id: Optional[UUID] = None
    sort_order: int
    is_active: bool
    document_count: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    children: List[CategoryOut] = []

    model_config = ConfigDict(from_attributes=True)


class CategoryRevisionOut(BaseModel):
    id: UUID
    category_id: Optional[UUID] = None
    revision: int
    action: str
    before_json: Optional[dict] = None
    after_json: Optional[dict] = None
    actor_user_id: Optional[UUID] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────
# P13-6: Integrity Report
# ──────────────────────────────────────────────

class IntegrityReportOut(BaseModel):
    id: UUID
    status: str
    total_documents: int
    total_chunks: int
    orphan_chunks: int
    missing_embeddings: int
    failed_documents: int
    stale_documents: int
    detail_json: Optional[dict] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────
# P13-7: KB Backup
# ──────────────────────────────────────────────

class KBBackupOut(BaseModel):
    id: UUID
    backup_type: str
    status: str
    file_path: Optional[str] = None
    file_size_bytes: Optional[int] = None
    document_count: Optional[int] = None
    chunk_count: Optional[int] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    initiated_by: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)


class KBBackupCreateIn(BaseModel):
    backup_type: str = "full"  # full | incremental


class KBRestoreIn(BaseModel):
    backup_id: UUID


# ──────────────────────────────────────────────
# P13-8: Usage Statistics
# ──────────────────────────────────────────────

class DepartmentUsageOut(BaseModel):
    department_id: Optional[UUID] = None
    department_name: str
    query_count: int
    generate_count: int
    total_tokens: int
    active_users: int


class TopDocumentOut(BaseModel):
    document_id: UUID
    filename: str
    query_hit_count: int
    last_queried: Optional[datetime] = None


class UsageReportOut(BaseModel):
    period_start: datetime
    period_end: datetime
    total_queries: int
    total_generations: int
    total_tokens: int
    active_users: int
    department_breakdown: List[DepartmentUsageOut] = []
    top_documents: List[TopDocumentOut] = []
    top_queries: List[TopQueryOut] = []
