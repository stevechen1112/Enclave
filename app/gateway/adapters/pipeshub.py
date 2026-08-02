"""
Phase 3 — PipesHub Adapter

將 PipesHub 的連接器與權限感知能力以 Adapter 契約整合進 Enclave Gateway。

整合範圍：
  - 企業連接器（NAS/SMB, SharePoint, Google Drive, Confluence, Jira...）
  - OAuth/service account credential lifecycle
  - 來源 ACL 繼承（external user/group/principal mapping）
  - 持續同步（webhook + polling + full reconciliation）
  - 權限感知檢索
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.authorization import AuthorizationContext
from app.gateway.adapters.base import BaseAdapter
from app.gateway.contracts import ChunkResult

logger = logging.getLogger(__name__)


class PipesHubAdapter(BaseAdapter):
    """
    PipesHub Sidecar Adapter。

    透過 HTTP/gRPC 呼叫 PipesHub 容器。
    """

    provider = "pipeshub"
    version = "1.0.0"

    def __init__(self, base_url: str = "http://pipeshub:8000", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._healthy = True

    # ── BaseAdapter 實作 ──────────────────────────────────────────────

    async def capabilities(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "version": self.version,
            "features": [
                "connector_sync", "source_acl", "permission_aware_search",
                "oauth_management", "webhook", "delta_sync",
            ],
            "connectors": [
                "nas_smb", "sharepoint", "google_drive", "confluence",
                "jira", "s3_minio", "github", "slack", "teams",
            ],
        }

    async def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy" if self._healthy else "unhealthy",
            "provider": self.provider,
            "version": self.version,
        }

    async def search(
        self,
        authz: AuthorizationContext,
        query: str,
        top_k: int = 20,
        scope: Optional[Dict[str, Any]] = None,
    ) -> List[ChunkResult]:
        """權限感知檢索。"""
        logger.debug(f"PipesHub search: query='{query[:50]}...'")
        return []

    async def ingest(
        self,
        document_id: UUID,
        revision: int,
        content_uri: str,
        content_hash: str,
        file_type: str,
        authz: AuthorizationContext,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise RuntimeError(
            "PipesHubAdapter stub cannot ingest; enable ENTERPRISE_CONNECT "
            "and use PipesHubHTTPAdapter"
        )

    async def delete(
        self,
        resource_type: str,
        resource_id: str,
        revision: int,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        raise RuntimeError("PipesHubAdapter stub cannot delete; use PipesHubHTTPAdapter")

    async def reconcile(
        self,
        resource_type: str,
        resource_id: str,
        desired_revision: int,
    ) -> Dict[str, Any]:
        return {
            "resource_id": resource_id,
            "desired_revision": desired_revision,
            "converged": False,
            "error": "stub_adapter_disabled",
        }

    # ── PipesHub 特有方法 ──────────────────────────────────────────────

    async def sync_connector(self, connector_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """觸發連接器同步。"""
        return {"connector_type": connector_type, "status": "sync_started"}

    async def get_connector_status(self, connector_type: str) -> Dict[str, Any]:
        """取得連接器同步狀態。"""
        return {"connector_type": connector_type, "status": "idle", "last_sync": None}

    async def sync_permissions(self, connector_type: str) -> List[Dict[str, Any]]:
        """同步來源 ACL。"""
        return []

    async def map_external_principal(
        self, provider: str, external_id: str, external_type: str,
    ) -> Optional[Dict[str, Any]]:
        """將外部 principal 映射到 Enclave 內部 subject。"""
        return None
