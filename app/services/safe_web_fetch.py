"""Bounded public-web fetcher for tenant supplied knowledge URLs."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx

MAX_WEB_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 5


class UnsafeSourceURL(ValueError):
    pass


def assert_public_http_url(
    value: str,
    *,
    resolver: Callable[..., list[tuple]] = socket.getaddrinfo,
) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise UnsafeSourceURL(
            "URL must use http(s), include a host, and omit credentials"
        )
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeSourceURL("local targets are not allowed")
    try:
        addresses = {row[4][0].split("%")[0] for row in resolver(hostname, parsed.port)}
    except OSError as exc:
        raise UnsafeSourceURL("URL host could not be resolved") from exc
    if not addresses:
        raise UnsafeSourceURL("URL host did not resolve")
    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise UnsafeSourceURL("URL host resolved to an invalid address") from exc
        if not address.is_global:
            raise UnsafeSourceURL(
                "private, loopback, link-local, and reserved targets are not allowed"
            )
    return parsed.geturl()


def fetch_public_web_page(url: str) -> bytes:
    """Fetch with redirect revalidation, no environment proxy, and a hard size cap."""
    current = str(url).strip()
    headers = {"User-Agent": "EnclaveKnowledgeFetcher/1.0"}
    with httpx.Client(
        timeout=20.0, follow_redirects=False, trust_env=False, headers=headers
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            current = assert_public_http_url(current)
            with client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeSourceURL("redirect response omitted location")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                declared = response.headers.get("content-length")
                if declared and int(declared) > MAX_WEB_BYTES:
                    raise ValueError("web source exceeds size limit")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_WEB_BYTES:
                        raise ValueError("web source exceeds size limit")
                return bytes(body)
    raise UnsafeSourceURL("web source exceeded redirect limit")
