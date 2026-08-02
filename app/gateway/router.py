"""
Phase 1 — Gateway Router

請求路由：依查詢類型（SearchDomain）分派到對應 Adapter。
支援多領域並行查詢與結果聚合。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.authorization import AuthorizationContext
from app.gateway.contracts import (
    SearchRequest, SearchDomain, ChunkResult,
    GatewayResponse, GatewayError, AuditTrail, SidecarAuthError,
)
from app.gateway.authorization import GatewayAuthorizer, PolicyDecision
from app.gateway.aggregator import ResultAggregator
from app.gateway.citation import CitationBuilder

logger = logging.getLogger(__name__)


class GatewayRouter:
    """
    Knowledge Gateway 路由器。

    職責：
      1. 接收 SearchRequest，依 domain 分派到 Adapter
      2. 執行授權檢查（PEP）
      3. 聚合多 Adapter 結果
      4. 產生稽核軌跡
    """

    def __init__(self, authorizer: Optional[GatewayAuthorizer] = None):
        self.authorizer = authorizer or GatewayAuthorizer()
        self._adapters: Dict[str, Any] = {}  # domain → adapter instance
        self._aggregator = ResultAggregator()
        self._citation_builder = CitationBuilder()

    def register_adapter(self, domain: str, adapter: Any):
        """註冊 Adapter。"""
        self._adapters[domain] = adapter
        logger.info(f"Adapter registered: {domain} → {type(adapter).__name__}")

    async def search(
        self,
        authz: AuthorizationContext,
        query: str,
        domain: SearchDomain = SearchDomain.HYBRID,
        top_k: int = 20,
        scope: Optional[Dict[str, Any]] = None,
        db=None,
    ) -> GatewayResponse:
        """
        執行授權檢索。

        流程：
          1. 授權檢查
          2. 依 domain 路由到 Adapter(s)
          3. 聚合結果
          4. 產生稽核軌跡
        """
        start_time = time.time()
        request_id = _generate_request_id()
        errors: List[GatewayError] = []
        providers_called: List[str] = []
        provider_latencies: Dict[str, int] = {}
        all_results: List[ChunkResult] = []

        # 1. 授權檢查
        decision = self.authorizer.authorize_search(authz, scope)
        if not decision.allowed:
            return GatewayResponse(
                request_id=request_id,
                status="error",
                provider="enclave",
                provider_version="1.0",
                errors=[GatewayError(
                    code="auth_error",
                    message=decision.reason,
                )],
                audit_trail=AuditTrail(
                    operation="search",
                    decisions=[f"denied:{decision.reason}"],
                ),
            )

        # 2. 決定要查詢的 Adapter(s)
        adapter_domains = self._resolve_domains(domain)

        # 3. 並行查詢
        tasks = []
        for d in adapter_domains:
            adapter = self._adapters.get(d)
            if adapter and hasattr(adapter, 'search'):
                tasks.append(self._query_adapter(
                    adapter, d, authz, query, top_k, scope, request_id,
                ))

        if not tasks:
            # 無可用 Adapter — 回退到 Enclave 主索引（由呼叫方處理）
            return GatewayResponse(
                request_id=request_id,
                status="partial",
                provider="enclave",
                provider_version="1.0",
                results=[],
                errors=[GatewayError(
                    code="no_adapter",
                    message=f"No adapter available for domain={domain.value}",
                )],
                audit_trail=AuditTrail(operation="search"),
            )

        adapter_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. 收集結果
        for i, result in enumerate(adapter_results):
            domain_name = adapter_domains[i]
            if isinstance(result, SidecarAuthError):
                # A5: auth failure is not retryable and must be loud.
                logger.error(
                    "SIDECAR_AUTH_FAILURE provider=%s status=%s request_id=%s",
                    result.provider, result.status_code, request_id,
                )
                errors.append(GatewayError(
                    code="auth_error",
                    message=str(result),
                    provider=domain_name,
                    retryable=False,
                    details={"http_status": result.status_code},
                ))
            elif isinstance(result, Exception):
                errors.append(GatewayError(
                    code="adapter_error",
                    message=str(result),
                    provider=domain_name,
                    retryable=True,
                ))
            elif isinstance(result, dict):
                providers_called.append(domain_name)
                provider_latencies[domain_name] = result.get("latency_ms", 0)
                all_results.extend(result.get("results", []))

        # 5. 聚合、去重、取 top_k
        aggregated = self._aggregator.aggregate(all_results, top_k=top_k * 2)

        # 5.5 後授權：deny set 立即排除；connector 必須 object-level source_record ACL
        filtered = []
        for r in aggregated:
            if r.document_id and self.authorizer.is_denied(str(r.document_id), authz.subject_id):
                continue
            provider = (r.provider or "").lower()
            meta = r.metadata or {}
            is_connector_hit = (
                provider in ("pipeshub", "connector")
                or meta.get("source_system")
                in ("nas_smb", "sharepoint", "google_drive", "local_fs")
                or (r.result_type or "") == "connector"
            )
            if is_connector_hit and not authz.has_kb_admin:
                source_system = meta.get("source_system")
                source_record_id = meta.get("source_record_id")
                if not self.authorizer.authorize_source_record(
                    authz, source_system, source_record_id, db=db,
                ):
                    continue
            filtered.append(r)
        aggregated = filtered[:top_k]

        citations = self._citation_builder.build(
            aggregated,
            acl_revision=authz.policy_revision,
            db=db,
        )

        # 6. 計算總延遲
        total_latency_ms = int((time.time() - start_time) * 1000)

        # 7. 決定整體狀態
        if not aggregated and errors:
            status = "error"
        elif errors:
            status = "partial"
        else:
            status = "success"

        return GatewayResponse(
            request_id=request_id,
            status=status,
            provider="enclave-gateway",
            provider_version="1.0",
            results=aggregated,
            citations=citations,
            errors=errors,
            audit_trail=AuditTrail(
                operation="search",
                providers_called=providers_called,
                total_latency_ms=total_latency_ms,
                provider_latencies=provider_latencies,
                decisions=decision.matched_rules,
            ),
        )

    def _resolve_domains(self, domain: SearchDomain) -> List[str]:
        """將 SearchDomain 解析為 Adapter domain 名稱列表。"""
        if domain == SearchDomain.HYBRID:
            # 並行查詢所有可用 Adapter
            return [d for d in ["document", "wiki", "graph", "connector"] if d in self._adapters]
        return [domain.value]

    async def _query_adapter(
        self,
        adapter: Any,
        domain: str,
        authz: AuthorizationContext,
        query: str,
        top_k: int,
        scope: Optional[Dict[str, Any]],
        request_id: str,
    ) -> Dict[str, Any]:
        """查詢單一 Adapter。"""
        start = time.time()
        try:
            results = await adapter.search(
                authz=authz,
                query=query,
                top_k=top_k,
                scope=scope,
            )
            latency_ms = int((time.time() - start) * 1000)
            return {
                "results": results,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            logger.error(f"Adapter {domain} search failed: {exc}")
            raise


def _generate_request_id() -> str:
    import uuid
    return str(uuid.uuid4())
