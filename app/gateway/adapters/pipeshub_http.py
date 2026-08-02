"""
Phase 3 ??PipesHub HTTP Client

真實 HTTP 呼叫 PipesHub 容器 API（OpenAPI /api/v1）。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from app.gateway.service_auth import build_service_headers, make_httpx_client
from app.core.authorization import AuthorizationContext
from app.gateway.adapters.base import BaseAdapter
from app.gateway.contracts import ChunkResult, SidecarAuthError
from app.gateway.resilience import CircuitBreaker

logger = logging.getLogger(__name__)

# Enclave connector_type → PipesHub resync connectorName.
# Values must match PipesHub's Connectors enum exactly (app/config/constants/arangodb.py).
_CONNECTOR_NAME_MAP: Dict[str, str] = {
    "sharepoint": "SHAREPOINT ONLINE",
    "google_drive": "DRIVE",
    "confluence": "CONFLUENCE",
    "jira": "JIRA",
    "nas_smb": "LOCAL_FS",
    "local_fs": "LOCAL_FS",
    "s3_minio": "MINIO",
    "s3": "S3",
    "github": "GITHUB",
    "slack": "SLACK",
    "teams": "MICROSOFT TEAMS",
    "bookstack": "BOOKSTACK",
    "nextcloud": "NEXTCLOUD",
}


class PipesHubHTTPAdapter(BaseAdapter):
    """PipesHub HTTP Adapter — 真實呼叫 PipesHub /api/v1 REST API。"""

    provider = "pipeshub"
    version = "1.0.0"

    def __init__(
        self,
        base_url: str = "http://pipeshub-api:3000",
        timeout: float = 60.0,
        api_key: Optional[str] = None,
        token_provider=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/api/v1"
        self.timeout = timeout
        self.api_key = api_key
        # A3: when a token provider is supplied it owns the credential and
        # auto-refreshes the 24h JWT; the static api_key is only a fallback.
        self._token_provider = token_provider
        self._circuit = CircuitBreaker(name="pipeshub", failure_threshold=3, recovery_timeout=60.0)

    async def _resolve_api_key(self) -> Optional[str]:
        if self._token_provider is not None:
            return await self._token_provider.get_token()
        return self.api_key

    async def _headers(self) -> Dict[str, str]:
        return build_service_headers(await self._resolve_api_key(), audience="pipeshub")

    async def capabilities(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "version": self.version,
            "base_url": self.base_url,
            "api_base": self.api_base,
            "features": [
                "connector_sync", "source_acl", "permission_aware_search",
                "oauth_management", "webhook", "delta_sync",
            ],
            "connectors": list(_CONNECTOR_NAME_MAP.keys()),
        }

    async def health(self) -> Dict[str, Any]:
        try:
            async with make_httpx_client(timeout=10.0) as client:
                resp = await client.get(f"{self.api_base}/health/services")
                if resp.status_code != 200:
                    return {
                        "status": "unhealthy",
                        "provider": self.provider,
                        "http_status": resp.status_code,
                    }
                data = resp.json()
                overall = data.get("status", "unhealthy")
                services = data.get("services") or {}
                core = ("query", "connector")
                core_ok = all(services.get(k) == "healthy" for k in core)
                status = "healthy" if overall == "healthy" or core_ok else "degraded"
                return {
                    "status": status,
                    "provider": self.provider,
                    "overall": overall,
                    "services": services,
                }
        except Exception as exc:
            return {"status": "unhealthy", "provider": self.provider, "error": str(exc)}

    async def search(
        self,
        authz: AuthorizationContext,
        query: str,
        top_k: int = 20,
        scope: Optional[Dict[str, Any]] = None,
    ) -> List[ChunkResult]:
        payload: Dict[str, Any] = {"query": query, "limit": top_k}
        if scope:
            payload["filters"] = scope.get("filters")
        try:
            async with make_httpx_client(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.api_base}/search",
                    json=payload,
                    headers=await self._headers(),
                )
                # A5 fail-closed: 401/403 must surface, not masquerade as "no results".
                if resp.status_code in (401, 403):
                    self._circuit.record_failure()
                    logger.error("PipesHub search auth failed: http %s", resp.status_code)
                    raise SidecarAuthError(self.provider, resp.status_code, resp.text[:200])
                if resp.status_code != 200:
                    logger.warning("PipesHub search HTTP %s: %s", resp.status_code, resp.text[:200])
                    return []
                data = resp.json()
                sr = data.get("searchResponse") or {}
                hits = sr.get("searchResults") or []
                records = {r.get("_id", r.get("id", "")): r for r in (sr.get("records") or [])}
                results: List[ChunkResult] = []
                for hit in hits[:top_k]:
                    rec_id = hit.get("recordId") or hit.get("record_id") or ""
                    rec = records.get(rec_id, {})
                    content = (
                        hit.get("content")
                        or hit.get("text")
                        or rec.get("content")
                        or rec.get("title")
                        or ""
                    )
                    results.append(
                        ChunkResult(
                            id=str(hit.get("id") or rec_id or hit.get("chunkId", "")),
                            content=str(content),
                            score=float(hit.get("score", hit.get("relevance", 0.0))),
                            result_type="connector_record",
                            document_id=rec_id or None,
                            provider=self.provider,
                            provider_version=self.version,
                        )
                    )
                return results
        except SidecarAuthError:
            raise
        except Exception as exc:
            logger.error("PipesHub search failed: %s", exc)
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
        """PipesHub is connector-driven; document ingest is a no-op acknowledgement only when healthy."""
        try:
            health = await self.health()
            if health.get("status") != "healthy":
                return {
                    "status": "error",
                    "error": "pipeshub_unhealthy",
                    "document_id": str(document_id),
                    "provider": self.provider,
                }
            return {
                "status": "skipped",
                "reason": "connector_owned",
                "document_id": str(document_id),
                "provider": self.provider,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc), "document_id": str(document_id)}

    async def delete(
        self,
        resource_type: str,
        resource_id: str,
        revision: int,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        try:
            async with make_httpx_client(timeout=30.0) as client:
                resp = await client.delete(
                    f"{self.api_base}/records/{resource_id}",
                    headers=await self._headers(),
                    params={"idempotency_key": idempotency_key},
                )
                if resp.status_code in (200, 204, 404):
                    return {"status": "deleted", "resource_id": resource_id, "provider": self.provider}
                return {
                    "status": "error",
                    "error": f"http_{resp.status_code}",
                    "resource_id": resource_id,
                }
        except Exception as exc:
            return {"status": "error", "error": str(exc), "resource_id": resource_id}

    async def reconcile(
        self,
        resource_type: str,
        resource_id: str,
        desired_revision: int,
    ) -> Dict[str, Any]:
        """Fail-closed: never pretend converged without evidence."""
        try:
            async with make_httpx_client(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.api_base}/records/{resource_id}",
                    headers=await self._headers(),
                )
                if resp.status_code == 404:
                    return {
                        "resource_id": resource_id,
                        "desired_revision": desired_revision,
                        "converged": desired_revision == 0,
                        "state": "missing",
                    }
                if resp.status_code != 200:
                    return {
                        "resource_id": resource_id,
                        "desired_revision": desired_revision,
                        "converged": False,
                        "error": f"http_{resp.status_code}",
                    }
                data = resp.json().get("data", resp.json())
                applied = int(data.get("revision", data.get("version", -1)))
                return {
                    "resource_id": resource_id,
                    "desired_revision": desired_revision,
                    "current_revision": applied,
                    "converged": applied >= desired_revision,
                }
        except Exception as exc:
            return {
                "resource_id": resource_id,
                "desired_revision": desired_revision,
                "converged": False,
                "error": str(exc),
            }

    # ?? PipesHub ?寞? ??

    def _connector_name(self, connector_type: str, config: Dict[str, Any]) -> str:
        if config.get("pipeshub_connector_name"):
            return str(config["pipeshub_connector_name"])
        return _CONNECTOR_NAME_MAP.get(connector_type.lower(), connector_type.upper())

    async def _list_connector_instances(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        resp = await client.get(
            f"{self.api_base}/connectors",
            headers=await self._headers(),
            params={"scope": "team", "limit": 200},
        )
        if resp.status_code != 200:
            return []
        body = resp.json()
        return body.get("data", body.get("connectors", [])) or []

    async def _resolve_pipeshub_connector_id(
        self, connector_type: str, config: Dict[str, Any], client: httpx.AsyncClient,
    ) -> Optional[str]:
        if config.get("pipeshub_connector_id"):
            return str(config["pipeshub_connector_id"])
        target_name = self._connector_name(connector_type, config)
        instances = await self._list_connector_instances(client)
        for inst in instances:
            inst_type = str(inst.get("connectorType") or inst.get("connector") or "").upper()
            inst_name = str(inst.get("name") or inst.get("instanceName") or "")
            if inst_type == target_name or inst_name.lower() == connector_type.lower():
                return str(inst.get("connectorId") or inst.get("id") or "")
        return None

    async def sync_connector(self, connector_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        觸發 PipesHub resync。
        說明：
          - PIPESHUB_ALLOW_MOCK=true 時允許以 mock_* 資源回傳 mode=mock
          - 若找不到對應 connector 或 HTTP 失敗，回傳 status=error，不偽裝 completed
        """
        mock_resources = list(config.get("mock_resources") or [])
        mock_acl = list(config.get("mock_acl_entries") or [])
        full_sync = bool(config.get("full_reindex") or config.get("fullSync"))
        allow_mock = (
            str(config.get("allow_mock", "")).lower() == "true"
            or __import__("os").getenv("PIPESHUB_ALLOW_MOCK", "false").lower() == "true"
        )
        try:
            from app.config import settings
            if settings.is_production:
                allow_mock = False
        except Exception:
            pass

        try:
            async with make_httpx_client(timeout=self.timeout) as client:
                connector_id = await self._resolve_pipeshub_connector_id(connector_type, config, client)
                if not connector_id:
                    if allow_mock and (mock_resources or mock_acl):
                        return {
                            "status": "completed",
                            "mode": "mock",
                            "resources": mock_resources,
                            "acl_entries": mock_acl,
                            "cursor": config.get("cursor", "mock-explicit"),
                        }
                    return {
                        "connector_type": connector_type,
                        "status": "error",
                        "error": f"no_pipeshub_connector_instance_for_{connector_type}",
                    }

                resp = await client.post(
                    f"{self.api_base}/connectors/{connector_id}/resync",
                    headers=await self._headers(),
                    json={
                        "connectorName": self._connector_name(connector_type, config),
                        "fullSync": full_sync,
                    },
                )
                if resp.status_code not in (200, 201, 202):
                    return {
                        "connector_type": connector_type,
                        "status": "error",
                        "error": f"resync_http_{resp.status_code}: {resp.text[:200]}",
                    }
                resync_body = resp.json()
                # resync 已觸發成功；若帶 mock 資源則回傳 completed + 該 resources（明確標示 mode=mock）。
                if allow_mock and (mock_resources or mock_acl):
                    return {
                        "status": "completed",
                        "mode": "mock",
                        "resources": mock_resources,
                        "acl_entries": mock_acl,
                        "cursor": config.get("cursor") or f"pipeshub-resync-{connector_id}",
                        "pipeshub_connector_id": connector_id,
                        "pipeshub_resync": resync_body,
                    }
                # 預設關閉 polling（PIPESHUB_POLL_AFTER_RESYNC=true 才啟用輪詢）。
                poll = str(config.get("poll_after_resync", "")).lower() == "true" or (
                    __import__("os").getenv("PIPESHUB_POLL_AFTER_RESYNC", "true").lower() == "true"
                )
                if poll:
                    polled = await self.poll_connector_records(
                        connector_id,
                        client=client,
                        max_attempts=int(config.get("poll_attempts", 6)),
                        delay_seconds=float(config.get("poll_delay_seconds", 2.0)),
                    )
                    if polled.get("resources"):
                        return {
                            "status": "completed",
                            "mode": "pipeshub_resync_polled",
                            "resources": polled["resources"],
                            "acl_entries": polled.get("acl_entries") or [],
                            "cursor": config.get("cursor") or f"pipeshub-resync-{connector_id}",
                            "pipeshub_connector_id": connector_id,
                            "pipeshub_resync": resync_body,
                            "poll": polled.get("meta"),
                        }
                return {
                    "status": "submitted",
                    "mode": "pipeshub_resync_pending",
                    "resources": [],
                    "acl_entries": [],
                    "cursor": config.get("cursor") or f"pipeshub-resync-{connector_id}",
                    "pipeshub_connector_id": connector_id,
                    "pipeshub_resync": resync_body,
                    "note": "async resync accepted; poll/webhook required before materialize",
                }
        except Exception as exc:
            if allow_mock and (mock_resources or mock_acl):
                logger.warning("PipesHub sync error (%s); explicit mock fallback", exc)
                return {
                    "status": "completed",
                    "mode": "mock_after_error",
                    "resources": mock_resources,
                    "acl_entries": mock_acl,
                    "cursor": config.get("cursor", "mock-after-error"),
                }
            return {"connector_type": connector_type, "status": "error", "error": str(exc)}

    async def get_connector_status(self, connector_type: str) -> Dict[str, Any]:
        try:
            async with make_httpx_client(timeout=30.0) as client:
                instances = await self._list_connector_instances(client)
                matched = [
                    i for i in instances
                    if str(i.get("connectorType", "")).lower() == connector_type.lower()
                ]
                return {
                    "connector_type": connector_type,
                    "status": "ok",
                    "instances": matched,
                    "count": len(matched),
                }
        except Exception as exc:
            return {"connector_type": connector_type, "status": "error", "error": str(exc)}

    async def poll_connector_records(
        self,
        connector_id: str,
        *,
        client: Optional[httpx.AsyncClient] = None,
        max_attempts: int = 6,
        delay_seconds: float = 2.0,
    ) -> Dict[str, Any]:
        """Poll PipesHub for records after async resync. Never invent resources."""
        import asyncio

        async def _poll(c: httpx.AsyncClient) -> Dict[str, Any]:
            meta: Dict[str, Any] = {"attempts": 0, "paths_tried": []}
            for attempt in range(max_attempts):
                meta["attempts"] = attempt + 1
                for path in (
                    f"/connectors/{connector_id}/records",
                    f"/connectors/{connector_id}/files",
                    f"/records",
                ):
                    meta["paths_tried"].append(path)
                    resp = await c.get(
                        f"{self.api_base}{path}",
                        headers=await self._headers(),
                        params={"connectorId": connector_id, "limit": 200},
                    )
                    if resp.status_code != 200:
                        continue
                    body = resp.json()
                    raw = body.get("data") or body.get("records") or body.get("files") or []
                    if not isinstance(raw, list) or not raw:
                        continue
                    resources = []
                    for item in raw:
                        if not isinstance(item, dict):
                            continue
                        rid = (
                            item.get("source_record_id")
                            or item.get("recordId")
                            or item.get("id")
                            or item.get("externalId")
                        )
                        if not rid:
                            continue
                        resources.append({
                            "source_record_id": str(rid),
                            "title": item.get("title") or item.get("name") or str(rid),
                            "content_hash": item.get("content_hash") or item.get("checksum"),
                            "source_version": item.get("version") or item.get("revision"),
                            "file_path": item.get("file_path") or item.get("downloadPath"),
                            "mime_type": item.get("mimeType") or item.get("mime_type"),
                        })
                    if resources:
                        acl = body.get("acl_entries") or body.get("permissions") or []
                        return {
                            "resources": resources,
                            "acl_entries": acl if isinstance(acl, list) else [],
                            "meta": meta,
                        }
                if attempt + 1 < max_attempts:
                    await asyncio.sleep(delay_seconds)
            return {"resources": [], "acl_entries": [], "meta": meta}

        if client is not None:
            return await _poll(client)
        async with make_httpx_client(timeout=self.timeout) as c:
            return await _poll(c)

    async def sync_permissions(self, connector_type: str) -> List[Dict[str, Any]]:
        """從 PipesHub 取得 connector ACL（盡量相容多種 API 形態）。"""
        try:
            async with make_httpx_client(timeout=self.timeout) as client:
                connector_id = await self._resolve_pipeshub_connector_id(
                    connector_type, {}, client,
                )
                if not connector_id:
                    return []
                # 依序嘗試常見的 ACL / permissions 端點
                for path in (
                    f"/connectors/{connector_id}/permissions",
                    f"/connectors/{connector_id}/acl",
                    f"/connectors/{connector_id}/records",
                ):
                    resp = await client.get(
                        f"{self.api_base}{path}",
                        headers=await self._headers(),
                        params={"limit": 200},
                    )
                    if resp.status_code != 200:
                        continue
                    body = resp.json()
                    entries = body.get("entries") or body.get("data") or body.get("records") or []
                    if isinstance(entries, list):
                        return entries
                return []
        except Exception as exc:
            logger.error("PipesHub permission sync failed: %s", exc)
            return []
