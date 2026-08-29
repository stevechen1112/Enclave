from app.packs.application_support import ModuleTenantEligibility
from app.platform.packs import (
    ApplicationDataPolicy, ApplicationManifest, PackContribution,
    PackDependency, PackManifest, UIModuleContribution,
    WorkflowHandlerContribution,
)


def build_training_knowhow_pack() -> PackContribution:
    return PackContribution(
        manifest=PackManifest(
            pack_key="training_knowhow",
            pack_version="1.0.0",
            display_name="Training and Know-how",
            capability_keys=(
                "knowledge.knowhow.read", "application.knowledge_interview"
            ),
            required_platform_capability_keys=(
                "workflow.task", "workflow.form", "workflow.approval"
            ),
            module_keys=("training_knowhow",),
            dependencies=(PackDependency("mka", "1.0.0"),),
        ),
        applications=(ApplicationManifest(
            application_key="training.knowhow",
            application_version="1.0.0",
            display_name="知識傳承與訓練",
            module_key="training_knowhow",
            owned_capability_keys=(
                "knowledge.knowhow.read", "application.knowledge_interview"
            ),
            required_platform_capability_keys=(
                "workflow.task", "workflow.form", "workflow.approval"
            ),
            task_keys=("interview", "training"),
            handler_keys=("interview", "training"),
            form_keys=("training_checklist", "meeting_visit"),
            data_policy=ApplicationDataPolicy(
                ownership_key="training.knowhow.records",
                removal_behavior="retain_by_policy",
                export_required_before_remove=False,
            ),
        ),),
        workflow_handlers=tuple(
            WorkflowHandlerContribution(
                handler_key=key,
                handler_version="1.0.0",
                module_key="training_knowhow",
                handler_path=f"app.packs.training_knowhow.handlers:{key}",
            )
            for key in ("interview", "training")
        ),
        ui_modules=(UIModuleContribution(
            ui_key="training_knowhow.workspace",
            ui_version="1.0.0",
            module_key="training_knowhow",
            route_keys=(
                "mka.knowhow.list", "mka.knowhow.interview", "mka.knowhow.detail"
            ),
            required_capability_keys=("knowledge.knowhow.read",),
            bundle_key="mka",
        ),),
        tenant_eligibility=ModuleTenantEligibility("training_knowhow"),
    )
