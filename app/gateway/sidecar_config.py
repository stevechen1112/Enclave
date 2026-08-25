"""Validated configuration for optional knowledge-engine sidecars.

Module flags are licenses/configuration intent.  They are deliberately kept
separate from runtime availability, which is established by health probes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.services.product_license import ProductModule, is_module_enabled


class SidecarConfigurationError(RuntimeError):
    """Raised when an enabled sidecar cannot be addressed safely."""


@dataclass(frozen=True)
class SidecarSpec:
    key: str
    module: ProductModule
    url_env: str
    default_url: str
    domains: tuple[str, ...]


SIDECAR_SPECS: tuple[SidecarSpec, ...] = (
    SidecarSpec(
        key="ragflow",
        module=ProductModule.DOCUMENT_INTELLIGENCE,
        url_env="RAGFLOW_BASE_URL",
        default_url="http://ragflow:9380",
        domains=("ragflow",),
    ),
    SidecarSpec(
        key="pipeshub",
        module=ProductModule.ENTERPRISE_CONNECT,
        url_env="PIPESHUB_BASE_URL",
        default_url="http://pipeshub-api:3000",
        domains=("connector",),
    ),
    SidecarSpec(
        key="weknora",
        module=ProductModule.KNOWLEDGE_COMPILER,
        url_env="WEKNORA_BASE_URL",
        default_url="http://weknora:8080",
        domains=("wiki", "graph"),
    ),
)

_SPEC_BY_KEY = {spec.key: spec for spec in SIDECAR_SPECS}
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _validate_url(spec: SidecarSpec, value: str, app_env: str) -> str:
    normalized = (value or "").strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SidecarConfigurationError(
            f"{spec.url_env} must be an absolute http(s) URL"
        )
    if parsed.username or parsed.password:
        raise SidecarConfigurationError(
            f"{spec.url_env} must not contain credentials; use secret variables"
        )
    if (
        (app_env or "").strip().lower() in {"production", "staging"}
        and parsed.hostname.lower() in _LOOPBACK_HOSTS
    ):
        raise SidecarConfigurationError(
            f"{spec.url_env} points to loopback in {app_env}; "
            "use the sidecar service DNS name"
        )
    return normalized


def resolve_sidecar_url(key: str, *, app_env: str | None = None) -> str:
    """Return a normalized, environment-safe URL for a known sidecar."""
    try:
        spec = _SPEC_BY_KEY[key]
    except KeyError as exc:
        raise SidecarConfigurationError(f"unknown sidecar: {key}") from exc
    env = app_env if app_env is not None else os.getenv("APP_ENV", "development")
    return _validate_url(spec, os.getenv(spec.url_env, spec.default_url), env)


def validate_enabled_sidecars(*, app_env: str | None = None) -> dict[str, str]:
    """Validate every enabled sidecar and return its safe URL.

    Disabled packs are intentionally ignored: an unused URL must not prevent
    the core product from starting.
    """
    urls: dict[str, str] = {}
    for spec in SIDECAR_SPECS:
        if is_module_enabled(spec.module):
            urls[spec.key] = resolve_sidecar_url(spec.key, app_env=app_env)
    return urls


def sidecar_configuration_states() -> dict[str, dict[str, object]]:
    """Non-secret configuration intent used by runtime health reporting."""
    states: dict[str, dict[str, object]] = {}
    for spec in SIDECAR_SPECS:
        states[spec.key] = {
            "module": spec.module.value,
            "enabled": bool(is_module_enabled(spec.module)),
            "domains": list(spec.domains),
        }
    return states
