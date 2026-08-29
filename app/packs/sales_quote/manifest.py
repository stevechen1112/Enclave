from app.packs.application_support import ModuleTenantEligibility
from app.platform.packs import (
    ApplicationDataPolicy,
    ApplicationManifest,
    PackContribution,
    PackManifest,
    UIModuleContribution,
    WorkflowHandlerContribution,
)


def build_sales_quote_pack() -> PackContribution:
    return PackContribution(
        manifest=PackManifest(
            pack_key="sales_quote",
            pack_version="1.0.0",
            display_name="Sales Quote",
            capability_keys=("application.sales_quote",),
            required_platform_capability_keys=(
                "workflow.task", "workflow.form", "workflow.approval"
            ),
            module_keys=("sales_quote",),
        ),
        applications=(ApplicationManifest(
            application_key="sales.quote",
            application_version="1.0.0",
            display_name="報價作業",
            module_key="sales_quote",
            owned_capability_keys=("application.sales_quote",),
            required_platform_capability_keys=(
                "workflow.task", "workflow.form", "workflow.approval"
            ),
            task_keys=("quote",),
            handler_keys=("quote",),
            form_keys=("quote",),
            data_policy=ApplicationDataPolicy(ownership_key="sales.quote.records"),
        ),),
        workflow_handlers=(WorkflowHandlerContribution(
            handler_key="quote",
            handler_version="1.0.0",
            module_key="sales_quote",
            handler_path="app.packs.sales_quote.handlers:quote",
        ),),
        ui_modules=(UIModuleContribution(
            ui_key="sales_quote.entry",
            ui_version="1.0.0",
            module_key="sales_quote",
            route_keys=("sales_quote.redirect",),
            required_capability_keys=("workflow.form",),
            bundle_key="sales_quote",
        ),),
        tenant_eligibility=ModuleTenantEligibility("sales_quote"),
    )
