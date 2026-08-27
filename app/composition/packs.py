"""Composition root for deployable product packs."""

from __future__ import annotations

from collections.abc import Mapping

from app.platform.packs import PackRegistry


def build_pack_registry(
    *, deployment_capabilities: Mapping[str, bool] | None = None
) -> PackRegistry:
    if deployment_capabilities is None:
        from app.config import settings

        deployment_capabilities = {"mka": bool(settings.PACK_MKA_ENABLED)}

    from app.packs.mka.manifest import build_mka_pack

    return PackRegistry(
        [build_mka_pack()], deployment_capabilities=deployment_capabilities
    )
