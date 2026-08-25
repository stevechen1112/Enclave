"""
Phase 1 — Gateway Health

Dependency readiness and degradation status for adapters.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.gateway.sidecar_config import sidecar_configuration_states
from app.services.product_license import ProductModule, is_module_enabled

logger = logging.getLogger(__name__)


class GatewayHealthChecker:
    """Aggregate adapter health into gateway readiness report."""

    async def check_adapters(self, adapters: dict[str, Any]) -> dict[str, Any]:
        adapter_status: dict[str, Any] = {}
        available_capabilities = []

        async def inspect(domain: str, adapter: Any):
            try:
                health = await adapter.health()
                capabilities = await adapter.capabilities() if health.get("status") == "healthy" else {}
                return domain, health, capabilities
            except Exception as exc:
                logger.error("Adapter %s health check failed: %s", domain, exc)
                return domain, {"status": "unhealthy", "reason": "probe_failed"}, {}

        results = await asyncio.gather(
            *(inspect(domain, adapter) for domain, adapter in adapters.items())
        )
        for domain, health, capabilities in results:
            status = health.get("status", "unhealthy")
            safe_health = {
                key: value for key, value in health.items()
                if key not in {"error", "base_url", "api_base"}
            }
            if "error" in health:
                logger.warning("Adapter %s unavailable: %s", domain, health["error"])
                safe_health["reason"] = "probe_failed"
            safe_health["available"] = status == "healthy"
            safe_health["features"] = list(capabilities.get("features") or [])
            adapter_status[domain] = safe_health
            if status == "healthy":
                available_capabilities.extend(safe_health["features"])

        total = len(adapters)
        healthy_count = sum(
            1 for item in adapter_status.values() if item.get("status") == "healthy"
        )
        core_healthy = adapter_status.get("document", {}).get("status") == "healthy"
        if core_healthy and healthy_count == total:
            overall = "healthy"
        elif core_healthy:
            overall = "degraded"
        else:
            overall = "unhealthy"

        configurations = sidecar_configuration_states()
        domain_states = adapter_status
        pack_states: dict[str, dict[str, Any]] = {
            ProductModule.BASE.value: {
                "enabled": True,
                "available": core_healthy,
                "state": "enabled" if core_healthy else "unavailable",
            }
        }
        for config in configurations.values():
            module = str(config["module"])
            enabled = bool(config["enabled"])
            domains = list(config["domains"])
            statuses = [domain_states.get(d, {}).get("status") for d in domains]
            available = enabled and bool(statuses) and all(s == "healthy" for s in statuses)
            degraded = enabled and any(s in {"healthy", "degraded"} for s in statuses)
            pack_states[module] = {
                "enabled": enabled,
                "available": available,
                "state": (
                    "disabled" if not enabled else
                    "enabled" if available else
                    "degraded" if degraded else
                    "unavailable"
                ),
            }
        automation_enabled = is_module_enabled(ProductModule.AGENT_AUTOMATION)
        pack_states[ProductModule.AGENT_AUTOMATION.value] = {
            "enabled": automation_enabled,
            "available": automation_enabled,
            "state": "enabled" if automation_enabled else "disabled",
        }

        return {
            "gateway": overall,
            "adapters": adapter_status,
            "healthy_adapters": healthy_count,
            "total_adapters": total,
            "available_capabilities": sorted(set(available_capabilities)),
            "packs": pack_states,
            "sidecars": configurations,
        }
