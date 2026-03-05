from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, computed_field, ConfigDict


class DocumentBase(BaseModel):
    filename: Optional[str] = None
    file_type: Optional[str] = None  # pdf, docx, doc, txt, xlsx, xls, csv, html, markdown, rtf, json, image
    status: Optional[str] = None  # uploading, parsing, embedding, completed, failed
    

class DocumentCreate(DocumentBase):
    filename: str
    file_type: str


class DocumentUpdate(BaseModel):
    status: Optional[str] = None
    error_message: Optional[str] = None
    chunk_count: Optional[int] = None
    quality_report: Optional[dict] = None  # QualityReport.to_dict()


class DocumentInDBBase(DocumentBase):
    id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    uploaded_by: Optional[UUID] = None
    file_size: Optional[int] = None
    chunk_count: Optional[int] = None
    error_message: Optional[str] = None
    quality_report: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# P10-3 ── 新入庫判斷閾值（7 天）
_NEW_THRESHOLD_DAYS = 7


class Document(DocumentInDBBase):
    @computed_field  # type: ignore[misc]
    @property
    def is_new(self) -> bool:
        """
        P10-3：文件是否為「最新入庫」狀態（7 天內新增或重新索引）。
        前端可根據此欄位顯示 NEW 標誌 icon。
        """
        ts = self.updated_at or self.created_at
        if not ts:
            return False
        now = datetime.now(timezone.utc)
        # 確保時區一致
        ts_aware = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return (now - ts_aware) < timedelta(days=_NEW_THRESHOLD_DAYS)


class DocumentChunkBase(BaseModel):
    chunk_index: Optional[int] = None
    text: Optional[str] = None
    chunk_hash: Optional[str] = None


class DocumentChunk(DocumentChunkBase):
    id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    vector_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
