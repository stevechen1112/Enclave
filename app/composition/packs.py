"""Composition root for deployable product packs."""

from __future__ import annotations

from collections.abc import Mapping

from app.platform.packs import PackContribution, PackRegistry


def build_pack_registry(
    *, deployment_capabilities: Mapping[str, bool] | None = None
) -> PackRegistry:
    if deployment_capabilities is None:
        from app.config import settings

        compatibility_enabled = bool(settings.PACK_MKA_ENABLED)
        deployment_capabilities = {
            "mka": compatibility_enabled,
            "sales_quote": (
                compatibility_enabled
                if settings.PACK_SALES_QUOTE_ENABLED is None
                else settings.PACK_SALES_QUOTE_ENABLED
            ),
            "incident_handover": (
                compatibility_enabled
                if settings.PACK_INCIDENT_HANDOVER_ENABLED is None
                else settings.PACK_INCIDENT_HANDOVER_ENABLED
            ),
            "quality_8d": (
                compatibility_enabled
                if settings.PACK_QUALITY_8D_ENABLED is None
                else settings.PACK_QUALITY_8D_ENABLED
            ),
            "training_knowhow": (
                compatibility_enabled
                if settings.PACK_TRAINING_KNOWHOW_ENABLED is None
                else settings.PACK_TRAINING_KNOWHOW_ENABLED
            ),
        }

    compatibility_default = bool(deployment_capabilities.get("mka", True))
    enabled = {
        "mka": compatibility_default,
        "sales_quote": bool(
            deployment_capabilities.get("sales_quote", compatibility_default)
        ),
        "incident_handover": bool(
            deployment_capabilities.get("incident_handover", compatibility_default)
        ),
        "quality_8d": bool(
            deployment_capabilities.get("quality_8d", compatibility_default)
        ),
        "training_knowhow": bool(
            deployment_capabilities.get("training_knowhow", compatibility_default)
        ),
    }

    # Import only Pack code selected for this deployment.  This is what makes
    # it possible to omit an application package from a build artifact instead
    # of merely hiding its routes after every implementation was imported.
    contributions: list[PackContribution] = []
    if enabled["mka"]:
        from app.packs.mka.manifest import build_mka_pack

        contributions.append(build_mka_pack())
    if enabled["sales_quote"]:
        from app.packs.sales_quote.manifest import build_sales_quote_pack

        contributions.append(build_sales_quote_pack())
    if enabled["incident_handover"]:
        from app.packs.incident_handover.manifest import build_incident_handover_pack

        contributions.append(build_incident_handover_pack())
    if enabled["quality_8d"]:
        from app.packs.quality_8d.manifest import build_quality_8d_pack

        contributions.append(build_quality_8d_pack())
    if enabled["training_knowhow"]:
        from app.packs.training_knowhow.manifest import build_training_knowhow_pack

        contributions.append(build_training_knowhow_pack())

    return PackRegistry(contributions)
