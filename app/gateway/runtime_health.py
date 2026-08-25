"""Process-local snapshot of verified gateway/sidecar runtime capabilities."""
from __future__ import annotations

import copy
import logging
from typing import Any

from app.gateway.health import GatewayHealthChecker

logger = logging.getLogger(__name__)

_snapshot: dict[str, Any] | None = None


def get_runtime_health_snapshot() -> dict[str, Any] | None:
    return copy.deepcopy(_snapshot)


def set_runtime_health_snapshot(report: dict[str, Any]) -> None:
    global _snapshot
    _snapshot = copy.deepcopy(report)


def reset_runtime_health_snapshot() -> None:
    """Clear process state during controlled reloads and isolated tests."""
    global _snapshot
    _snapshot = None


async def probe_gateway_runtime() -> dict[str, Any]:
    """Build configured adapters, probe them concurrently, and cache the truth."""
    from app.gateway.runtime import get_configured_health_adapters

    report = await GatewayHealthChecker().check_adapters(
        get_configured_health_adapters()
    )
    set_runtime_health_snapshot(report)
    logger.info(
        "Gateway capability probe: status=%s available=%s",
        report.get("gateway"),
        report.get("available_capabilities", []),
    )
    return report
