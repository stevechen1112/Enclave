"""MKA pack manifest and platform contributions."""

from __future__ import annotations

from sqlalchemy import func, or_

from app.packs.mka.knowledge_provider import ApprovedKnowhowProvider
from app.platform.packs import (
    APIRouterContribution,
    ApplicationDataPolicy,
    ApplicationManifest,
    LifecycleHookContribution,
    PackContribution,
    PackManifest,
    PackTenantContext,
    PermissionResolverContribution,
    ProjectorContribution,
    ReviewProviderContribution,
    TaskHandlerContribution,
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

        query = context.db.query(TenantModuleBinding.id).filter(
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
        return query.first() is not None


def build_mka_pack() -> PackContribution:
    return PackContribution(
        manifest=PackManifest(
            pack_key="mka",
            pack_version="1.0.0",
            display_name="Manufacturing Knowledge Applications",
            capability_keys=(
                "knowledge.knowhow.read",
                "application.knowledge_interview",
                "application.sales_quote",
                "application.incident_handover",
                "application.quality_8d",
            ),
            required_platform_capability_keys=(
                "workflow.task",
                "workflow.form",
                "workflow.approval",
            ),
            module_keys=MKA_MODULE_KEYS,
            permission_keys=(
                "mka.knowhow.read",
                "mka.knowhow.write",
                "mka.approval.decide",
                "mka.module.admin",
            ),
            metadata={"owner": "manufacturing-applications", "stability": "beta"},
        ),
        applications=(
            ApplicationManifest(
                application_key="sales.quote",
                application_version="1.0.0",
                display_name="報價作業",
                module_key="sales_quote",
                owned_capability_keys=("application.sales_quote",),
                required_platform_capability_keys=(
                    "workflow.task",
                    "workflow.form",
                    "workflow.approval",
                ),
                task_keys=("quote",),
                handler_keys=("quote",),
                form_keys=("quote",),
                data_policy=ApplicationDataPolicy(
                    ownership_key="sales.quote.records"
                ),
            ),
            ApplicationManifest(
                application_key="operations.incident_handover",
                application_version="1.0.0",
                display_name="異常與交接",
                module_key="incident_handover",
                owned_capability_keys=("application.incident_handover",),
                required_platform_capability_keys=(
                    "workflow.task",
                    "workflow.form",
                    "workflow.approval",
                ),
                task_keys=("incident", "handover", "daily_report"),
                handler_keys=("incident", "handover", "daily_report"),
                form_keys=(
                    "incident_report",
                    "shift_handover",
                    "equipment_repair",
                    "daily_report",
                ),
                data_policy=ApplicationDataPolicy(
                    ownership_key="operations.incident_handover.records"
                ),
            ),
            ApplicationManifest(
                application_key="quality.8d",
                application_version="1.0.0",
                display_name="品質 8D／CAPA",
                module_key="quality_8d",
                owned_capability_keys=("application.quality_8d",),
                required_platform_capability_keys=(
                    "workflow.task",
                    "workflow.form",
                    "workflow.approval",
                ),
                task_keys=("quality_8d",),
                handler_keys=("quality_8d",),
                form_keys=("quality_8d", "capa"),
                data_policy=ApplicationDataPolicy(
                    ownership_key="quality.8d.records"
                ),
            ),
            ApplicationManifest(
                application_key="training.knowhow",
                application_version="1.0.0",
                display_name="知識傳承與訓練",
                module_key="training_knowhow",
                owned_capability_keys=(
                    "knowledge.knowhow.read",
                    "application.knowledge_interview",
                ),
                required_platform_capability_keys=(
                    "workflow.task",
                    "workflow.form",
                    "workflow.approval",
                ),
                permission_keys=("mka.knowhow.read", "mka.knowhow.write"),
                task_keys=("interview", "training"),
                handler_keys=("interview", "training"),
                form_keys=("training_checklist", "meeting_visit"),
                data_policy=ApplicationDataPolicy(
                    ownership_key="training.knowhow.records",
                    removal_behavior="retain_by_policy",
                    export_required_before_remove=False,
                ),
            ),
        ),
        knowledge_providers=(ApprovedKnowhowProvider(),),
        task_handlers=(
            TaskHandlerContribution(
                handler_key="mka.long_interview.transcribe",
                handler_version="1.0.0",
                task_name="tasks.transcribe_knowledge_capture",
                handler_path="app.tasks.mka_tasks.transcribe_knowledge_capture",
            ),
            TaskHandlerContribution(
                handler_key="mka.audio.retention",
                handler_version="1.0.0",
                task_name="tasks.purge_mka_retention",
                handler_path="app.tasks.mka_tasks.purge_mka_retention",
            ),
        ),
        projectors=(
            ProjectorContribution(
                projector_key="mka.capture.asset",
                projector_version="1.0.0",
                source_kinds=("audio",),
                artifact_kinds=("chunk_manifest",),
                projector_path="app.services.asset_projection.finalize_capture_asset_revision",
            ),
            ProjectorContribution(
                projector_key="mka.capture.transcript",
                projector_version="1.0.0",
                source_kinds=("audio",),
                artifact_kinds=("transcript_segment",),
                projector_path="app.services.asset_projection.project_capture_transcript_segments",
            ),
        ),
        ui_modules=(
            UIModuleContribution(
                ui_key="mka.workspace",
                ui_version="1.0.0",
                route_keys=(
                    "mka.job.home",
                    "mka.job.task",
                    "mka.forms.mine",
                    "mka.forms.instance",
                    "mka.forms.form",
                    "mka.approvals",
                ),
                required_capability_keys=("workflow.approval", "workflow.form"),
                navigation=({"to": "/job", "label": "現場作業"},),
                bundle_key="mka",
                default_home="/job",
            ),
            UIModuleContribution(
                ui_key="mka.sales_quote",
                ui_version="1.0.0",
                module_key="sales_quote",
                route_keys=("mka.quote.redirect",),
                required_capability_keys=("workflow.form",),
                bundle_key="mka",
            ),
            UIModuleContribution(
                ui_key="mka.knowhow",
                ui_version="1.0.0",
                module_key="training_knowhow",
                route_keys=(
                    "mka.knowhow.list",
                    "mka.knowhow.interview",
                    "mka.knowhow.detail",
                ),
                required_capability_keys=("knowledge.knowhow.read",),
                bundle_key="mka",
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
        review_providers=(
            ReviewProviderContribution(
                provider_key="mka.knowledge_review",
                provider_version="1.0.0",
                provider_path="app.packs.mka.reviews:MKAReviewProvider",
            ),
        ),
        tenant_eligibility=MKATenantEligibility(),
    )
