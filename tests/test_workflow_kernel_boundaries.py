"""Architecture and compatibility gates for the shared Workflow Kernel."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.models import mka as legacy_models
from app.models import workflow as workflow_models
from app.platform.workflow import (
    TASK_STATUS_TRANSITIONS,
    WORKFLOW_CAPABILITY_KEYS,
    can_transition_task,
)


ROOT = Path(__file__).resolve().parents[1]


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_workflow_models_own_existing_tables_without_schema_duplication() -> None:
    expected = {
        "form_definitions",
        "form_instances",
        "rule_sets",
        "approval_policies",
        "mka_approval_requests",
        "mka_task_definitions",
        "mka_task_runs",
        "mka_task_run_events",
        "mka_form_templates",
    }
    actual = {
        workflow_models.FormDefinition.__table__.name,
        workflow_models.FormInstance.__table__.name,
        workflow_models.RuleSet.__table__.name,
        workflow_models.ApprovalPolicy.__table__.name,
        workflow_models.WorkflowApprovalRequest.__table__.name,
        workflow_models.TaskDefinition.__table__.name,
        workflow_models.TaskRun.__table__.name,
        workflow_models.TaskRunEvent.__table__.name,
        workflow_models.FormTemplate.__table__.name,
    }
    assert actual == expected


def test_mka_model_imports_are_compatibility_aliases_only() -> None:
    assert legacy_models.FormDefinition is workflow_models.FormDefinition
    assert legacy_models.FormInstance is workflow_models.FormInstance
    assert legacy_models.RuleSet is workflow_models.RuleSet
    assert legacy_models.ApprovalPolicy is workflow_models.ApprovalPolicy
    assert legacy_models.MKAApprovalRequest is workflow_models.WorkflowApprovalRequest
    assert legacy_models.TaskDefinition is workflow_models.TaskDefinition
    assert legacy_models.TaskRun is workflow_models.TaskRun
    assert legacy_models.TaskRunEvent is workflow_models.TaskRunEvent
    assert legacy_models.FormTemplate is workflow_models.FormTemplate


def test_workflow_kernel_does_not_import_mka_or_application_packs() -> None:
    targets = [
        ROOT / "app" / "models" / "workflow.py",
        ROOT / "app" / "platform" / "workflow" / "contracts.py",
        ROOT / "app" / "services" / "task_engine.py",
        ROOT / "app" / "services" / "task_metrics.py",
        ROOT / "app" / "services" / "form_template_service.py",
    ]
    violations: list[str] = []
    for path in targets:
        for imported in _absolute_imports(path):
            if imported.startswith(("app.models.mka", "app.packs")):
                violations.append(f"{path.relative_to(ROOT)}:{imported}")
    assert violations == []


def test_workflow_repository_is_independent_from_application_persistence() -> None:
    from app.services.workflow_repository import WorkflowRepository

    catalog = json.loads(
        (ROOT / "config" / "application_boundary_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    assert catalog["workflow_compatibility_bridges"] == []
    assert hasattr(WorkflowRepository, "create_form_instance")
    assert hasattr(WorkflowRepository, "decide_approval")
    assert not hasattr(WorkflowRepository, "create_knowhow")
    imports = _absolute_imports(ROOT / "app/services/workflow_repository.py")
    assert "app.services.mka_persistence" not in imports
    assert "app.models.mka" not in imports
    for relative in (
        "app/api/v1/endpoints/forms.py",
        "app/api/v1/endpoints/mka_approvals.py",
    ):
        imports = _absolute_imports(ROOT / relative)
        assert "app.services.mka_persistence" not in imports
        assert "app.services.workflow_repository" in imports


def test_task_engine_contains_no_application_handler_implementation() -> None:
    source = (ROOT / "app/services/task_engine.py").read_text(encoding="utf-8")
    for vocabulary in (
        "quote",
        "incident",
        "handover",
        "quality_8d",
        "training",
        "interview",
        "mka_persistence",
    ):
        assert vocabulary not in source


def test_shared_workflow_routers_are_not_owned_by_mka_pack() -> None:
    base_source = (ROOT / "app" / "api" / "v1" / "api.py").read_text(
        encoding="utf-8"
    )
    pack_source = (ROOT / "app" / "packs" / "mka" / "api.py").read_text(
        encoding="utf-8"
    )
    for router_name in ("tasks", "forms", "mka_approvals", "form_templates"):
        assert f"api_router.include_router({router_name}.router" in base_source
        assert f"router.include_router({router_name}.router" not in pack_source


def test_workflow_state_contract_is_domain_neutral_and_immutable() -> None:
    assert WORKFLOW_CAPABILITY_KEYS == (
        "workflow.task",
        "workflow.form",
        "workflow.approval",
        "workflow.todo",
        "workflow.notification",
        "workflow.export",
    )
    assert can_transition_task("draft", "in_progress")
    assert not can_transition_task("exported", "draft")
    with pytest.raises(TypeError):
        TASK_STATUS_TRANSITIONS["draft"] = frozenset()  # type: ignore[index]
