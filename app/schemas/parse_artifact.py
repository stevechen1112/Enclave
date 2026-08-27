"""ParseArtifact schema — RAGFlow parse output contract."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class BBox(BaseModel):
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0


class ParsePage(BaseModel):
    page_num: int
    bbox: Optional[BBox] = None
    reading_order: int = 0
    text: Optional[str] = None


class ParseTable(BaseModel):
    page: int = 1
    rows: int = 0
    columns: int = 0
    cells: List[Dict[str, Any]] = Field(default_factory=list)


class ParseChunk(BaseModel):
    text: str
    template: str = "general"
    hierarchy: List[str] = Field(default_factory=list)
    page: Optional[int] = None
    bbox: Optional[BBox] = None
    chunk_index: int = 0
    section: Optional[str] = None
    worksheet: Optional[str] = None
    table_name: Optional[str] = None
    row_number: Optional[int] = None
    column_name: Optional[str] = None
    cell_range: Optional[str] = None


class ParseArtifact(BaseModel):
    parser: str = "enclave/native"
    version: str = "1.0.0"
    source_hash: str = ""
    document_id: str = ""
    document_revision: int = 1
    pages: List[ParsePage] = Field(default_factory=list)
    tables: List[ParseTable] = Field(default_factory=list)
    chunks: List[ParseChunk] = Field(default_factory=list)
    warnings: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    elapsed_ms: int = 0
    ocr_used: bool = False
    vlm_used: bool = False
    # DD-H09：parse 路徑若已寫入 RAGFlow，帶上 provider id 供 outbox 改走 reconcile
    provider: Optional[str] = None
    provider_resource_ids: List[str] = Field(default_factory=list)
    # A1：記錄上游實際設定（layout_recognize_actual 等），供 label_integrity 閘門查核
    metadata: Dict[str, Any] = Field(default_factory=dict)
