"""
IP Whitelist Middleware for Admin API Network Isolation (T4-4)

Restricts access to admin-only API endpoints (/api/v1/admin/*, /api/v1/analytics/*)
to requests originating from whitelisted IP addresses or CIDR ranges.

Configuration via environment variables:
  ADMIN_IP_WHITELIST: comma-separated list of IPs/CIDRs (default: 127.0.0.1,::1)
  ADMIN_IP_WHITELIST_ENABLED: true/false (default: false in dev, true in prod)
"""

import ipaddress
import logging
from collections.abc import Sequence

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import settings

logger = logging.getLogger(__name__)

# ─── Admin-only path prefixes ───
ADMIN_PATH_PREFIXES = (
    "/api/v1/admin",
    "/api/v1/analytics",
    "/api/v1/admin/",
    "/api/v1/analytics/",
)


def parse_whitelist(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse comma-separated IP/CIDR string into network objects."""
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            # Try as network first (e.g. 10.0.0.0/8)
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("Invalid IP/CIDR in ADMIN_IP_WHITELIST: %s", entry)
    return networks


def get_client_ip(
    request: Request,
    trusted_proxies: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> str:
    """
    Extract real client IP.
    Only trust forwarded headers when the immediate peer is trusted, then walk
    the chain from right to left so a client-supplied leftmost value cannot
    bypass IP controls.
    """
    direct_ip = request.client.host if request.client else ""

    if direct_ip and is_ip_allowed(direct_ip, trusted_proxies):
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            raw_hops = [value.strip() for value in forwarded.split(",")]
            try:
                hops = [ipaddress.ip_address(value) for value in raw_hops]
                direct = ipaddress.ip_address(direct_ip)
            except ValueError:
                logger.warning("Invalid X-Forwarded-For chain; using direct peer")
                return direct_ip

            for hop in reversed([*hops, direct]):
                if not any(hop in network for network in trusted_proxies):
                    return str(hop)
            return str(hops[0]) if hops else direct_ip

        x_real = request.headers.get("X-Real-IP")
        if x_real:
            try:
                return str(ipaddress.ip_address(x_real.strip()))
            except ValueError:
                logger.warning("Invalid X-Real-IP value; using direct peer")

    return direct_ip or "0.0.0.0"


def is_ip_allowed(
    client_ip: str,
    whitelist: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """Check if the client IP is within any whitelisted network."""
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return any(addr in net for net in whitelist)


class AdminIPWhitelistMiddleware(BaseHTTPMiddleware):
    """
    Middleware that blocks non-whitelisted IPs from admin API endpoints.

    Enabled via ADMIN_IP_WHITELIST_ENABLED env var.
    Whitelist configured via ADMIN_IP_WHITELIST env var (comma-separated IPs/CIDRs).
    """

    def __init__(self, app, **kwargs):  # type: ignore
        super().__init__(app, **kwargs)
        self.enabled: bool = getattr(settings, "ADMIN_IP_WHITELIST_ENABLED", False)
        raw_whitelist: str = getattr(settings, "ADMIN_IP_WHITELIST", "127.0.0.1,::1")
        self.whitelist = parse_whitelist(raw_whitelist)
        raw_trusted: str = getattr(settings, "ADMIN_TRUSTED_PROXY_IPS", "127.0.0.1,::1")
        self.trusted_proxies = parse_whitelist(raw_trusted)

        if self.enabled:
            logger.info(
                "Admin IP whitelist enabled — allowed networks: %s",
                [str(n) for n in self.whitelist],
            )
        else:
            logger.info("Admin IP whitelist is DISABLED (development mode)")

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip if disabled
        if not self.enabled:
            return await call_next(request)

        # Only check admin paths
        path = request.url.path
        if not any(path.startswith(prefix) for prefix in ADMIN_PATH_PREFIXES):
            return await call_next(request)

        # Check client IP
        client_ip = get_client_ip(request, self.trusted_proxies)
        if is_ip_allowed(client_ip, self.whitelist):
            return await call_next(request)

        # Blocked
        logger.warning(
            "Admin API access denied — IP=%s path=%s", client_ip, path
        )
        return Response(
            content='{"detail":"Access denied: IP not in admin whitelist"}',
            status_code=403,
            media_type="application/json",
        )
