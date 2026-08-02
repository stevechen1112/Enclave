"""
Phase 1 — Gateway Health

Dependency readiness and degradation status for adapters.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class GatewayHealthChecker:
    """Aggregate adapter health into gateway readiness report."""

    async def check_adapters(self, adapters: Dict[str, Any]) -> Dict[str, Any]:
        adapter_status: Dict[str, Any] = {}
        healthy_count = 0
        for domain, adapter in adapters.items():
            try:
                health = await adapter.health()
                adapter_status[domain] = health
                if health.get("status") == "healthy":
                    healthy_count += 1
            except Exception as exc:
                logger.error("Adapter %s health check failed: %s", domain, exc)
                adapter_status[domain] = {"status": "error", "error": str(exc)}

        total = len(adapters)
        if total == 0:
            overall = "degraded"
        elif healthy_count == total:
            overall = "healthy"
        elif healthy_count > 0:
            overall = "degraded"
        else:
            overall = "unhealthy"

        return {
            "gateway": overall,
            "adapters": adapter_status,
            "healthy_adapters": healthy_count,
            "total_adapters": total,
        }
