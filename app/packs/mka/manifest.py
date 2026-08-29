"""MKA pack manifest and platform contributions."""

from __future__ import annotations

from sqlalchemy import func, or_

from app.platform.packs import (
    APIRouterContribution,
    LifecycleHookContribution,
    PackContribution,
    PackManifest,
    PackTenantContext,
    PermissionResolverContribution,
    UIModuleContribution,
)

MKA_MODULE_KEYS = (
    "sales_quote",
    "incident_handover",
    "quality_8d",
    "training_knowhow",
)


class MKATenantEligibility:
    """Tenant entitlement remains data-driven and independent of deployment flags."""

    def is_enabled(self, context: PackTenantContext) -> bool:
        from app.models.mka import TenantModuleBinding

        query = context.db.query(TenantModuleBinding).filter(
            TenantModuleBinding.tenant_id == context.tenant_id,
            TenantModuleBinding.enabled.is_(True),
            TenantModuleBinding.license_state.in_(["trial", "active"]),
            or_(
                TenantModuleBinding.effective_from.is_(None),
                TenantModuleBinding.effective_from <= func.now(),
            ),
            or_(
                TenantModuleBinding.effective_to.is_(None),
                TenantModuleBinding.effective_to > func.now(),
            ),
        )
        if context.module_key is not None:
            if context.module_key not in MKA_MODULE_KEYS:
                return False
            query = query.filter(TenantModuleBinding.module_key == context.module_key)
        else:
            query = query.filter(TenantModuleBinding.module_key.in_(MKA_MODULE_KEYS))
        for binding in query.all():
            lifecycle = dict(
                (binding.config_json or {}).get("_application_lifecycle") or {}
            )
            if lifecycle and lifecycle.get("state") != "enabled":
                continue
            return True
        return False


def build_mka_pack() -> PackContribution:
    return PackContribution(
        manifest=PackManifest(
            pack_key="mka",
            pack_version="1.0.0",
            display_name="Manufacturing Knowledge Applications",
            capability_keys=(
                "mka.workspace",
            ),
            required_platform_capability_keys=(
                "workflow.task",
                "workflow.form",
                "workflow.approval",
            ),
            module_keys=(),
            permission_keys=(
                "mka.knowhow.read",
                "mka.knowhow.write",
                "mka.approval.decide",
                "mka.module.admin",
            ),
            metadata={"owner": "manufacturing-applications", "stability": "beta"},
        ),
        ui_modules=(
            UIModuleContribution(
                ui_key="mka.workspace",
                ui_version="1.0.0",
                route_keys=(
                    "workflow.job.home",
                    "workflow.job.task",
                    "workflow.forms.mine",
                    "workflow.forms.instance",
                    "workflow.forms.form",
                    "workflow.approvals",
                ),
                required_capability_keys=("workflow.approval", "workflow.form"),
                navigation=({"to": "/job", "label": "現場作業"},),
                bundle_key="workflow",
                default_home="/job",
            ),
        ),
        api_routers=(
            APIRouterContribution(
                router_key="mka.api",
                router_version="1.0.0",
                router_path="app.packs.mka.api:router",
            ),
        ),
        permission_resolvers=(
            PermissionResolverContribution(
                resolver_key="mka.permissions",
                resolver_version="1.0.0",
                resolver_path="app.packs.mka.permissions:resolve_permissions",
            ),
        ),
        lifecycle_hooks=(
            LifecycleHookContribution(
                hook_key="mka.tenant.provision",
                hook_version="1.0.0",
                event_key="tenant.provisioned",
                hook_path="app.packs.mka.lifecycle:provision_tenant",
            ),
        ),
        tenant_eligibility=MKATenantEligibility(),
    )
