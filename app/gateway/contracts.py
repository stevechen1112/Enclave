"""
Phase 1 — Gateway Contracts (版本化 Schema)

定義 Gateway 與 Adapter 之間的版本化契約。
所有跨服務通訊使用這些型別，確保向後相容。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID


# ═══════════════════════════════════════════════════════════════════════════════
#  Request / Response Envelope
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class GatewayRequest:
    """統一 Gateway 請求信封。"""
    request_id: str
    correlation_id: str
    tenant_id: UUID
    authz_snapshot: Dict[str, Any]  # AuthorizationContext 的序列化
    deadline_ms: int = 30000
    idempotency_key: Optional[str] = None


@dataclass
class GatewayResponse:
    """統一 Gateway 回應信封。"""
    request_id: str
    status: str  # success | partial | error
    provider: str
    provider_version: str
    results: List[Any] = field(default_factory=list)
    citations: List[Citation] = field(default_factory=list)
    errors: List[GatewayError] = field(default_factory=list)
    audit_trail: Optional[AuditTrail] = None


# ═══════════════════════════════════════════════════════════════════════════════
#  Search Contracts
# ═══════════════════════════════════════════════════════════════════════════════

class SearchDomain(str, Enum):
    """檢索領域 — 決定路由到哪個 Adapter。"""
    DOCUMENT = "document"        # Enclave 主索引
    WIKI = "wiki"                # WeKnora Wiki
    GRAPH = "graph"              # GraphRAG
    CONNECTOR = "connector"      # PipesHub 企業脈絡
    HYBRID = "hybrid"            # 多領域合併


@dataclass
class SearchRequest(GatewayRequest):
    """檢索請求。"""
    query: str = ""
    domain: SearchDomain = SearchDomain.HYBRID
    top_k: int = 20
    scope: Optional[Dict[str, Any]] = None  # SearchScope 序列化
    filters: Optional[Dict[str, Any]] = None


@dataclass
class ChunkResult:
    """單一檢索結果（chunk/wiki/graph entity）。"""
    id: str
    content: str
    score: float
    result_type: str  # chunk | wiki_page | graph_entity | connector_record
    document_id: Optional[str] = None
    document_revision: Optional[int] = None
    provider: str = "enclave"
    provider_version: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
#  Citation
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Citation:
    """統一引用格式。"""
    citation_id: str
    canonical_document_id: UUID
    document_revision: int
    canonical_resource_type: str = "document"
    canonical_resource_id: Optional[str] = None
    artifact_id: Optional[str] = None       # chunk/wiki/entity ID
    artifact_type: str = "chunk"            # chunk | wiki_page | graph_entity
    source_system: Optional[str] = None     # google_drive | sharepoint | ...
    source_record_id: Optional[str] = None
    page: Optional[int] = None
    bbox: Optional[Dict[str, float]] = None  # {x, y, w, h}
    section: Optional[str] = None
    provider: str = "enclave"
    provider_version: str = ""
    acl_revision: int = 1
    content_hash: Optional[str] = None
    retrieval_score: Optional[float] = None
    rerank_score: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════════════
#  Ingest / Delete Contracts
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class IngestRequest(GatewayRequest):
    """文件擷取請求。"""
    document_id: UUID = field(default_factory=UUID)
    document_revision: int = 1
    content_uri: str = ""                   # signed URL or object storage reference
    content_hash: str = ""
    file_type: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeleteRequest(GatewayRequest):
    """資源刪除請求。"""
    resource_type: str = ""                 # document | chunk | wiki_page
    resource_id: str = ""
    resource_revision: int = 1
    reason: str = "user_request"


# ═══════════════════════════════════════════════════════════════════════════════
#  Error & Audit
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class GatewayError:
    """結構化錯誤。"""
    code: str                               # timeout | auth_error | provider_unavailable | invalid_request
    message: str
    provider: Optional[str] = None
    retryable: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


class SidecarAuthError(Exception):
    """A5 — sidecar 回 401/403。

    Adapter 在收到 401/403 時必須拋出此例外，而非靜默回傳空結果，
    讓 router 將其記為 error（整體狀態轉 partial/error）並留下可告警訊號。
    靜默回空會讓呼叫端誤判為「查無資料」，掩蓋憑證失效。
    """

    def __init__(self, provider: str, status_code: int, detail: str = ""):
        self.provider = provider
        self.status_code = status_code
        super().__init__(
            f"{provider} sidecar auth failed (http {status_code})"
            + (f": {detail}" if detail else "")
        )


@dataclass
class AuditTrail:
    """Gateway 操作稽核軌跡。"""
    operation: str                          # search | ingest | delete
    providers_called: List[str] = field(default_factory=list)
    total_latency_ms: int = 0
    provider_latencies: Dict[str, int] = field(default_factory=dict)
    token_usage: Dict[str, int] = field(default_factory=dict)  # provider → tokens
    decisions: List[str] = field(default_factory=list)          # routing/deny decisions
    # ADR-009 融合觀測（FusionPolicy v1）
    fusion_policy_version: str = ""
    query_domain: str = ""
    dropped_non_citable: int = 0
