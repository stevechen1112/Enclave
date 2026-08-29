from app.packs.application_support import ModuleTenantEligibility
from app.platform.packs import (
    ApplicationDataPolicy, ApplicationManifest, PackContribution,
    PackManifest, WorkflowHandlerContribution,
)


def build_incident_handover_pack() -> PackContribution:
    handlers = tuple(
        WorkflowHandlerContribution(
            handler_key=key,
            handler_version="1.0.0",
            module_key="incident_handover",
            handler_path=f"app.packs.incident_handover.handlers:{key}",
        )
        for key in ("incident", "handover", "daily_report")
    )
    return PackContribution(
        manifest=PackManifest(
            pack_key="incident_handover",
            pack_version="1.0.0",
            display_name="Incident and Handover",
            capability_keys=("application.incident_handover",),
            required_platform_capability_keys=(
                "workflow.task", "workflow.form", "workflow.approval"
            ),
            module_keys=("incident_handover",),
        ),
        applications=(ApplicationManifest(
            application_key="operations.incident_handover",
            application_version="1.0.0",
            display_name="異常與交接",
            module_key="incident_handover",
            owned_capability_keys=("application.incident_handover",),
            required_platform_capability_keys=(
                "workflow.task", "workflow.form", "workflow.approval"
            ),
            task_keys=("incident", "handover", "daily_report"),
            handler_keys=("incident", "handover", "daily_report"),
            form_keys=(
                "incident_report", "shift_handover", "equipment_repair", "daily_report"
            ),
            data_policy=ApplicationDataPolicy(
                ownership_key="operations.incident_handover.records"
            ),
        ),),
        workflow_handlers=handlers,
        tenant_eligibility=ModuleTenantEligibility("incident_handover"),
    )
