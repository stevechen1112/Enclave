from app.packs.application_support import ModuleTenantEligibility
from app.packs.training_knowhow.knowledge_provider import ApprovedKnowhowProvider
from app.platform.packs import (
    APIRouterContribution, ApplicationDataPolicy, ApplicationManifest,
    PackContribution, PackManifest, ProjectorContribution,
    ReviewProviderContribution, TaskHandlerContribution,
    UIModuleContribution, WorkflowHandlerContribution,
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
        knowledge_providers=(ApprovedKnowhowProvider(),),
        task_handlers=(
            TaskHandlerContribution(
                handler_key="training_knowhow.long_interview.transcribe",
                handler_version="1.0.0",
                task_name="tasks.transcribe_knowledge_capture",
                handler_path="app.tasks.mka_tasks.transcribe_knowledge_capture",
            ),
            TaskHandlerContribution(
                handler_key="training_knowhow.audio.retention",
                handler_version="1.0.0",
                task_name="tasks.purge_mka_retention",
                handler_path="app.tasks.mka_tasks.purge_mka_retention",
            ),
        ),
        projectors=(
            ProjectorContribution(
                projector_key="training_knowhow.capture.asset",
                projector_version="1.0.0",
                source_kinds=("audio",),
                artifact_kinds=("chunk_manifest",),
                projector_path="app.services.asset_projection.finalize_capture_asset_revision",
            ),
            ProjectorContribution(
                projector_key="training_knowhow.capture.transcript",
                projector_version="1.0.0",
                source_kinds=("audio",),
                artifact_kinds=("transcript_segment",),
                projector_path="app.services.asset_projection.project_capture_transcript_segments",
            ),
        ),
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
        api_routers=(APIRouterContribution(
            router_key="training_knowhow.api",
            router_version="1.0.0",
            router_path="app.packs.training_knowhow.api:router",
        ),),
        review_providers=(ReviewProviderContribution(
            provider_key="training_knowhow.knowledge_review",
            provider_version="1.0.0",
            provider_path="app.packs.training_knowhow.reviews:MKAReviewProvider",
        ),),
        tenant_eligibility=ModuleTenantEligibility("training_knowhow"),
    )
