from app.packs.application_support import ModuleTenantEligibility
from app.platform.packs import (
    ApplicationDataPolicy, ApplicationManifest, PackContribution,
    PackManifest, WorkflowHandlerContribution,
)


def build_quality_8d_pack() -> PackContribution:
    return PackContribution(
        manifest=PackManifest(
            pack_key="quality_8d",
            pack_version="1.0.0",
            display_name="Quality 8D/CAPA",
            capability_keys=("application.quality_8d",),
            required_platform_capability_keys=(
                "workflow.task", "workflow.form", "workflow.approval"
            ),
            module_keys=("quality_8d",),
        ),
        applications=(ApplicationManifest(
            application_key="quality.8d",
            application_version="1.0.0",
            display_name="品質 8D／CAPA",
            module_key="quality_8d",
            owned_capability_keys=("application.quality_8d",),
            required_platform_capability_keys=(
                "workflow.task", "workflow.form", "workflow.approval"
            ),
            task_keys=("quality_8d",),
            handler_keys=("quality_8d",),
            form_keys=("quality_8d", "capa"),
            data_policy=ApplicationDataPolicy(ownership_key="quality.8d.records"),
        ),),
        workflow_handlers=(WorkflowHandlerContribution(
            handler_key="quality_8d",
            handler_version="1.0.0",
            module_key="quality_8d",
            handler_path="app.packs.quality_8d.handlers:quality_8d",
        ),),
        tenant_eligibility=ModuleTenantEligibility("quality_8d"),
    )
