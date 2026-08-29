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
    from app.packs.incident_handover.manifest import build_incident_handover_pack
    from app.packs.quality_8d.manifest import build_quality_8d_pack
    from app.packs.sales_quote.manifest import build_sales_quote_pack
    from app.packs.training_knowhow.manifest import build_training_knowhow_pack

    return PackRegistry(
        [
            build_mka_pack(),
            build_sales_quote_pack(),
            build_incident_handover_pack(),
            build_quality_8d_pack(),
            build_training_knowhow_pack(),
        ],
        deployment_capabilities={
            "mka": bool(deployment_capabilities.get("mka", True)),
            "sales_quote": bool(deployment_capabilities.get("sales_quote", deployment_capabilities.get("mka", True))),
            "incident_handover": bool(deployment_capabilities.get("incident_handover", deployment_capabilities.get("mka", True))),
            "quality_8d": bool(deployment_capabilities.get("quality_8d", deployment_capabilities.get("mka", True))),
            "training_knowhow": bool(deployment_capabilities.get("training_knowhow", deployment_capabilities.get("mka", True))),
        },
    )
