"""
Phase 1 — Gateway Adapter Factory

Centralized adapter construction for Gateway API and Outbox Worker.
Disabled packs are OMITTED (never mount stubs that fake converged=True).
"""
from __future__ import annotations

import logging
import os
from typing import Dict

from app.gateway.adapters.base import BaseAdapter
from app.gateway.adapters.enclave import EnclaveCanonicalAdapter
from app.services.product_license import ProductModule, is_module_enabled

logger = logging.getLogger(__name__)

# Always project to enclave; optional packs added only when enabled
PROJECTION_PROVIDERS = ("enclave", "ragflow", "weknora", "pipeshub")

def _sidecar_url(key: str) -> str:
    from app.gateway.sidecar_config import resolve_sidecar_url

    return resolve_sidecar_url(key)


def _build_ragflow_adapter() -> BaseAdapter:
    from app.gateway.adapters.ragflow_http import RAGFlowHTTPAdapter

    return RAGFlowHTTPAdapter(
        base_url=_sidecar_url("ragflow"),
        api_key=os.getenv("RAGFLOW_API_KEY", ""),
    )


def build_document_search_adapter() -> BaseAdapter:
    """Canonical search always uses Enclave index."""
    return EnclaveCanonicalAdapter()


def build_gateway_adapters() -> Dict[str, BaseAdapter]:
    """Search fan-out adapters. Disabled packs are omitted."""
    adapters: Dict[str, BaseAdapter] = {
        "document": build_document_search_adapter(),
    }

    if is_module_enabled(ProductModule.ENTERPRISE_CONNECT):
        from app.gateway.adapters.pipeshub_http import PipesHubHTTPAdapter
        from app.gateway.token_provider import build_pipeshub_token_provider
        adapters["connector"] = PipesHubHTTPAdapter(
            base_url=_sidecar_url("pipeshub"),
            api_key=os.getenv("PIPESHUB_API_KEY", ""),
            token_provider=build_pipeshub_token_provider(),
        )

    if is_module_enabled(ProductModule.KNOWLEDGE_COMPILER):
        from app.gateway.adapters.weknora_http import WeKnoraHTTPAdapter
        from app.gateway.token_provider import build_weknora_token_provider
        wek = WeKnoraHTTPAdapter(
            base_url=_sidecar_url("weknora"),
            api_key=os.getenv("WEKNORA_API_KEY", ""),
            token_provider=build_weknora_token_provider(),
        )
        adapters["wiki"] = wek
        adapters["graph"] = wek

    return adapters


def build_projection_adapters() -> Dict[str, BaseAdapter]:
    """
    Outbox projection adapters.
    Disabled packs MUST NOT appear (stubs that fake success are forbidden).
    """
    adapters: Dict[str, BaseAdapter] = {
        "enclave": EnclaveCanonicalAdapter(),
    }

    if is_module_enabled(ProductModule.DOCUMENT_INTELLIGENCE):
        adapters["ragflow"] = _build_ragflow_adapter()

    if is_module_enabled(ProductModule.ENTERPRISE_CONNECT):
        from app.gateway.adapters.pipeshub_http import PipesHubHTTPAdapter
        from app.gateway.token_provider import build_pipeshub_token_provider
        adapters["pipeshub"] = PipesHubHTTPAdapter(
            base_url=_sidecar_url("pipeshub"),
            api_key=os.getenv("PIPESHUB_API_KEY", ""),
            token_provider=build_pipeshub_token_provider(),
        )

    if is_module_enabled(ProductModule.KNOWLEDGE_COMPILER):
        from app.gateway.adapters.weknora_http import WeKnoraHTTPAdapter
        from app.gateway.token_provider import build_weknora_token_provider
        adapters["weknora"] = WeKnoraHTTPAdapter(
            base_url=_sidecar_url("weknora"),
            api_key=os.getenv("WEKNORA_API_KEY", ""),
            token_provider=build_weknora_token_provider(),
        )

    logger.info("Projection adapters: %s", list(adapters.keys()))
    return adapters


def active_projection_providers() -> tuple[str, ...]:
    """Providers that will actually be dispatched."""
    return tuple(build_projection_adapters().keys())


def build_health_adapters() -> Dict[str, BaseAdapter]:
    """All enabled runtime dependencies, including projection-only RAGFlow."""
    adapters = build_gateway_adapters()
    if is_module_enabled(ProductModule.DOCUMENT_INTELLIGENCE):
        adapters["ragflow"] = _build_ragflow_adapter()
    return adapters
