"""Process-wide GatewayRouter with adapters registered (never an empty router)."""
from __future__ import annotations

import logging
import threading
from typing import Optional

from app.gateway.adapter_factory import build_gateway_adapters, build_health_adapters
from app.gateway.authorization import get_gateway_authorizer
from app.gateway.router import GatewayRouter

logger = logging.getLogger(__name__)

_gateway_router: Optional[GatewayRouter] = None
_health_adapters = None
_gateway_lock = threading.Lock()


def get_configured_gateway_router() -> GatewayRouter:
    """Singleton GatewayRouter with search adapters mounted."""
    global _gateway_router
    if _gateway_router is not None:
        return _gateway_router

    with _gateway_lock:
        if _gateway_router is not None:
            return _gateway_router

        try:
            authorizer = get_gateway_authorizer()
        except Exception as exc:
            raise RuntimeError(
                "GatewayAuthorizer singleton unavailable; refusing empty deny cache"
            ) from exc

        router = GatewayRouter(authorizer=authorizer)
        adapters = build_gateway_adapters()
        for domain, adapter in adapters.items():
            router.register_adapter(domain, adapter)
        logger.info("GatewayRouter initialized with adapters: %s", list(adapters.keys()))
        _gateway_router = router
        return _gateway_router


def get_configured_health_adapters():
    """Singleton set used by startup and operator health probes."""
    global _health_adapters
    if _health_adapters is None:
        with _gateway_lock:
            if _health_adapters is None:
                _health_adapters = build_health_adapters()
    return _health_adapters
