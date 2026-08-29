"""Domain-neutral Workflow persistence implementation.

Application-specific approval side effects are delegated through composition;
this module never imports MKA models, services, or application packs.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.workflow import (
    ApprovalPolicy,
    FormDefinition,
    FormInstance,
    WorkflowApprovalRequest,
)
from app.services.fixed_form import (
    FieldType,
    FixedFormCalculator,
    FixedFormSchema,
    FixedFormValidator,
    FormField,
    get_form_registry,
)

logger = logging.getLogger(__name__)


class WorkflowPersistenceError(ValueError):
    pass


class WorkflowNotFoundError(WorkflowPersistenceError):
    pass


class WorkflowConflictError(WorkflowPersistenceError):
    pass


class WorkflowForbiddenError(WorkflowPersistenceError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _copy_json(value: Any) -> Any:
    """Produce a detached, JSON-compatible immutable snapshot."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _field_to_dict(field: FormField) -> Dict[str, Any]:
    return {
        "name": field.name,
        "label": field.label,
        "type": field.type.value,
        "required": field.required,
        "default": field.default,
        "options": list(field.options),
        "min_value": field.min_value,
        "max_value": field.max_value,
        "precision": field.precision,
        "currency": field.currency,
        "description": field.description,
        "calculated": field.calculated,
        "formula": field.formula,
    }


def _schema_to_json(schema: FixedFormSchema) -> Dict[str, Any]:
    return {
        "name": schema.name,
        "version": schema.version,
        "description": schema.description,
        "require_approval": schema.require_approval,
        "approver_roles": list(schema.approver_roles),
        "fields": [_field_to_dict(field) for field in schema.fields],
    }


def _schema_from_definition(definition: FormDefinition) -> FixedFormSchema:
    payload = dict(definition.json_schema or {})
    fields = []
    for item in payload.get("fields", []):
        item = dict(item)
        item["type"] = FieldType(item["type"])
        fields.append(FormField(**item))
    return FixedFormSchema(
        name=payload.get("name") or definition.form_key,
        version=payload.get("version") or definition.schema_version,
        description=payload.get("description") or definition.name,
        fields=fields,
        require_approval=payload.get("require_approval", True),
        approver_roles=list(payload.get("approver_roles") or ["owner", "admin"]),
    )


def form_definition_to_dict(row: FormDefinition) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
        "form_key": row.form_key,
        "name": row.name,
        "schema_version": row.schema_version,
        "json_schema": row.json_schema or {},
        "ui_schema": row.ui_schema or {},
        "status": row.status,
        "approval_policy_id": str(row.approval_policy_id) if row.approval_policy_id else None,
    }


def form_instance_to_dict(row: FormInstance) -> Dict[str, Any]:
    form_key = None
    try:
        from sqlalchemy.orm import object_session
        from app.models.workflow import FormDefinition as _FormDefinition

        db = object_session(row)
        if db is not None and row.form_definition_id:
            defn = db.query(_FormDefinition).filter(_FormDefinition.id == row.form_definition_id).first()
            form_key = defn.form_key if defn else None
    except Exception:
        form_key = None
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "form_definition_id": str(row.form_definition_id),
        "form_key": form_key,
        "form_version": row.form_version,
        "module_key": row.module_key,
        "owner_id": str(row.owner_id),
        "status": row.status,
        "record_version": row.record_version,
        "values": row.values_json or {},
        "provenance": row.provenance_json or {},
        "calculation_snapshot": row.calculation_snapshot or {},
        "validation_result": row.validation_result or {},
        "scene_context": row.scene_context or {},
        "approval_request_id": str(row.approval_request_id) if row.approval_request_id else None,
        "immutable_snapshot": row.immutable_snapshot or {},
        "export_artifacts": row.export_artifacts or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def approval_to_dict(row: WorkflowApprovalRequest) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "approval_policy_id": str(row.approval_policy_id) if row.approval_policy_id else None,
        "object_type": row.object_type,
        "object_id": str(row.object_id),
        "policy_version": row.policy_version,
        "current_step": row.current_step,
        "record_version": row.record_version,
        "status": row.status,
        "submitted_by": str(row.submitted_by),
        "idempotency_key": row.idempotency_key,
        "reviewers": row.reviewers or [],
        "decision_log": row.decision_log or [],
        "immutable_snapshot": row.immutable_snapshot or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }



class WorkflowRepository:
    """Tenant-scoped Workflow repository backed by the caller session."""

    _FORM_MUTABLE_STATES = {"draft", "changes_requested", "rejected"}

    def __init__(self, db: Session):
        self.db = db

    def ensure_form_definitions(self, *, tenant_id: UUID) -> List[FormDefinition]:
        """Lazily materialize built-in forms as tenant-owned definitions."""
        registry = get_form_registry()
        rows: List[FormDefinition] = []
        for form_key in registry.list_forms():
            schema = registry.get(form_key)
            if schema is None:
                continue
            row = (
                self.db.query(FormDefinition)
                .filter(
                    FormDefinition.tenant_id == tenant_id,
                    FormDefinition.form_key == form_key,
                    FormDefinition.schema_version == schema.version,
                )
                .first()
            )
            if row is None:
                policy = ApprovalPolicy(
                    tenant_id=tenant_id,
                    module_key="fixed_form",
                    object_type="form",
                    version=schema.version,
                    status="active",
                    risk_level="medium",
                    steps=[
                        {
                            "name": "business_review",
                            "roles": list(schema.approver_roles or ["owner", "admin"]),
                        }
                    ],
                )
                self.db.add(policy)
                self.db.flush()
                row = FormDefinition(
                    tenant_id=tenant_id,
                    form_key=form_key,
                    name=schema.description or schema.name,
                    schema_version=schema.version,
                    json_schema=_schema_to_json(schema),
                    ui_schema={},
                    output_templates=[],
                    approval_policy_id=policy.id,
                    status="active",
                )
                self.db.add(row)
                self.db.flush()
            rows.append(row)
        return rows

    def list_form_definitions(self, *, tenant_id: UUID) -> List[FormDefinition]:
        self.ensure_form_definitions(tenant_id=tenant_id)
        return (
            self.db.query(FormDefinition)
            .filter(
                FormDefinition.tenant_id == tenant_id,
                FormDefinition.status == "active",
            )
            .order_by(FormDefinition.form_key.asc())
            .all()
        )

    def get_form_definition(
        self, *, tenant_id: UUID, form_key: str
    ) -> FormDefinition:
        self.ensure_form_definitions(tenant_id=tenant_id)
        row = (
            self.db.query(FormDefinition)
            .filter(
                FormDefinition.tenant_id == tenant_id,
                FormDefinition.form_key == form_key,
                FormDefinition.status == "active",
            )
            .order_by(FormDefinition.created_at.desc())
            .first()
        )
        if row is None:
            raise WorkflowNotFoundError(f"form definition not found: {form_key}")
        return row

    def validate_form_values(
        self,
        *,
        tenant_id: UUID,
        form_key: str,
        values: Dict[str, Any],
    ) -> Dict[str, Any]:
        """以租戶 DB 的 FormDefinition 驗證一組值（不落地 instance）。

        與 create/validate_form 同一條 schema 來源，避免 endpoint 走記憶體
        registry 造成租戶專屬表單規則不一致。
        """
        definition = self.get_form_definition(tenant_id=tenant_id, form_key=form_key)
        schema = _schema_from_definition(definition)
        errors = FixedFormValidator.validate(schema, dict(values or {}))
        return {
            "valid": not errors,
            "errors": errors,
            "schema_version": schema.version,
        }

    def create_form_instance(
        self,
        *,
        tenant_id: UUID,
        owner_id: UUID,
        form_key: str,
        values: Optional[Dict[str, Any]] = None,
        provenance: Optional[Dict[str, Any]] = None,
        module_key: Optional[str] = None,
        scene_context: Optional[Dict[str, Any]] = None,
    ) -> FormInstance:
        definition = self.get_form_definition(tenant_id=tenant_id, form_key=form_key)
        schema = _schema_from_definition(definition)
        initial = {
            field.name: field.default
            for field in schema.fields
            if field.default is not None
        }
        # SceneContext 預填：僅填 schema 已有且尚未提供的欄位
        scene = _copy_json(scene_context or {})
        field_names = {f.name for f in schema.fields}
        for key in (
            "equipment_id", "equipment_model", "work_order_id", "product_id",
            "part_number", "customer_id", "site_id", "plant_id", "line_id",
        ):
            if key in field_names and key not in (values or {}) and scene.get(key):
                initial[key] = scene[key]
        initial.update(values or {})
        row = FormInstance(
            tenant_id=tenant_id,
            form_definition_id=definition.id,
            form_version=definition.schema_version,
            module_key=module_key,
            owner_id=owner_id,
            status="draft",
            record_version=1,
            values_json=_copy_json(initial),
            provenance_json=_copy_json(provenance or {}),
            scene_context=scene,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get_form_instance(
        self,
        *,
        tenant_id: UUID,
        instance_id: UUID,
        actor_id: UUID,
        actor_roles: Iterable[str] = (),
        is_superuser: bool = False,
    ) -> FormInstance:
        row = self._get_form_instance(tenant_id, instance_id)
        self._authorize_form_actor(
            row,
            actor_id=actor_id,
            actor_roles=actor_roles,
            is_superuser=is_superuser,
        )
        return row

    def patch_form_instance(
        self,
        *,
        tenant_id: UUID,
        instance_id: UUID,
        actor_id: UUID,
        actor_roles: Iterable[str] = (),
        is_superuser: bool = False,
        expected_version: int,
        values: Dict[str, Any],
        provenance: Optional[Dict[str, Any]] = None,
    ) -> FormInstance:
        row = self._get_form_instance(tenant_id, instance_id, for_update=True)
        self._authorize_form_actor(
            row, actor_id=actor_id, actor_roles=actor_roles, is_superuser=is_superuser
        )
        self._check_form_mutable(row)
        self._check_version(row.record_version, expected_version)
        merged = dict(row.values_json or {})
        merged.update(_copy_json(values))
        row.values_json = merged
        merged_provenance = dict(row.provenance_json or {})
        merged_provenance.update(_copy_json(provenance or {}))
        row.provenance_json = merged_provenance
        row.validation_result = {}
        row.record_version += 1
        self.db.flush()
        return row

    def calculate_form(
        self,
        *,
        tenant_id: UUID,
        instance_id: UUID,
        actor_id: UUID,
        actor_roles: Iterable[str] = (),
        is_superuser: bool = False,
        expected_version: int,
    ) -> FormInstance:
        row = self._get_form_instance(tenant_id, instance_id, for_update=True)
        self._authorize_form_actor(
            row, actor_id=actor_id, actor_roles=actor_roles, is_superuser=is_superuser
        )
        self._check_form_mutable(row)
        self._check_version(row.record_version, expected_version)
        definition = self._form_definition_for_instance(tenant_id, row)
        schema = _schema_from_definition(definition)
        values = dict(row.values_json or {})
        provenance = dict(row.provenance_json or {})
        calculated: Dict[str, Any] = {}
        for field in schema.fields:
            if not field.calculated:
                continue
            result = FixedFormCalculator.calculate(field, values)
            if result is not None:
                values[field.name] = result
                calculated[field.name] = result
                provenance[field.name] = {
                    "source": "deterministic_rule",
                    "formula": field.formula,
                    "schema_version": schema.version,
                }
        row.values_json = values
        row.provenance_json = provenance
        row.calculation_snapshot = {
            "schema_version": schema.version,
            "calculated": calculated,
            "calculated_at": _now().isoformat(),
        }
        row.record_version += 1
        self.db.flush()
        return row

    def validate_form(
        self,
        *,
        tenant_id: UUID,
        instance_id: UUID,
        actor_id: UUID,
        actor_roles: Iterable[str] = (),
        is_superuser: bool = False,
        expected_version: int,
    ) -> FormInstance:
        row = self._get_form_instance(tenant_id, instance_id, for_update=True)
        self._authorize_form_actor(
            row, actor_id=actor_id, actor_roles=actor_roles, is_superuser=is_superuser
        )
        self._check_form_mutable(row)
        self._check_version(row.record_version, expected_version)
        definition = self._form_definition_for_instance(tenant_id, row)
        schema = _schema_from_definition(definition)
        errors = FixedFormValidator.validate(schema, dict(row.values_json or {}))
        row.validation_result = {
            "valid": not errors,
            "errors": errors,
            "schema_version": schema.version,
            "validated_at": _now().isoformat(),
        }
        row.record_version += 1
        self.db.flush()
        return row

    def submit_form(
        self,
        *,
        tenant_id: UUID,
        instance_id: UUID,
        submitted_by: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[FormInstance, WorkflowApprovalRequest]:
        row = self._get_form_instance(tenant_id, instance_id, for_update=True)
        if submitted_by != row.owner_id:
            raise WorkflowForbiddenError("only the form owner may submit this form")
        existing = (
            self.db.query(WorkflowApprovalRequest)
            .filter(
                WorkflowApprovalRequest.tenant_id == tenant_id,
                WorkflowApprovalRequest.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing is not None:
            if existing.object_type != "form" or existing.object_id != instance_id:
                raise WorkflowConflictError("idempotency key belongs to another object")
            return row, existing

        self._check_form_mutable(row)
        self._check_version(row.record_version, expected_version)
        definition = self._form_definition_for_instance(tenant_id, row)
        schema = _schema_from_definition(definition)

        values = dict(row.values_json or {})
        provenance = dict(row.provenance_json or {})
        calculated: Dict[str, Any] = {}
        for field in schema.fields:
            if field.calculated:
                result = FixedFormCalculator.calculate(field, values)
                if result is not None:
                    values[field.name] = result
                    calculated[field.name] = result
                    provenance[field.name] = {
                        "source": "deterministic_rule",
                        "formula": field.formula,
                        "schema_version": schema.version,
                    }
        errors = FixedFormValidator.validate(schema, values)
        if errors:
            raise WorkflowConflictError("form validation failed: " + "; ".join(errors))

        snapshot = _copy_json(
            {
                "form_definition_id": str(definition.id),
                "form_key": definition.form_key,
                "schema_version": definition.schema_version,
                "values": values,
                "provenance": provenance,
                "calculation": calculated,
                "submitted_by": str(submitted_by),
                "submitted_at": _now().isoformat(),
            }
        )
        policy = self._approval_policy(
            tenant_id=tenant_id,
            policy_id=definition.approval_policy_id,
            object_type="form",
        )
        approval = WorkflowApprovalRequest(
            tenant_id=tenant_id,
            approval_policy_id=policy.id,
            object_type="form",
            object_id=row.id,
            policy_version=policy.version,
            current_step=0,
            record_version=1,
            status="pending",
            submitted_by=submitted_by,
            idempotency_key=idempotency_key,
            reviewers=self._step_roles(policy, 0),
            decision_log=[],
            immutable_snapshot=snapshot,
        )
        self.db.add(approval)
        self.db.flush()
        row.values_json = values
        row.provenance_json = provenance
        row.calculation_snapshot = {
            "schema_version": schema.version,
            "calculated": calculated,
        }
        row.validation_result = {"valid": True, "errors": []}
        row.immutable_snapshot = snapshot
        row.approval_request_id = approval.id
        row.status = "pending_review"
        row.record_version += 1
        self.db.flush()
        return row, approval

    _EXPORT_FORMATS = ("pdf", "docx", "xlsx", "md")

    def assert_form_exportable(
        self,
        *,
        tenant_id: UUID,
        instance_id: UUID,
        actor_id: UUID,
        actor_roles: Iterable[str] = (),
        is_superuser: bool = False,
    ) -> FormInstance:
        """匯出預檢（非同步匯出排程前呼叫）：授權＋已核准＋snapshot 存在。"""
        row = self.get_form_instance(
            tenant_id=tenant_id,
            instance_id=instance_id,
            actor_id=actor_id,
            actor_roles=actor_roles,
            is_superuser=is_superuser,
        )
        if row.status != "approved":
            raise WorkflowConflictError(
                f"form is not approved; export forbidden while status={row.status}"
            )
        if not (row.immutable_snapshot or {}):
            raise WorkflowConflictError("approved form is missing immutable snapshot")
        return row

    def export_form(
        self,
        *,
        tenant_id: UUID,
        instance_id: UUID,
        actor_id: UUID,
        actor_roles: Iterable[str] = (),
        is_superuser: bool = False,
        format: str = "pdf",
        artifact_extra: Optional[Dict[str, Any]] = None,
    ):
        """Render an approved form from its immutable snapshot.

        計畫硬性規則（MKA-P2 Exit）：未核准不可正式匯出；匯出內容必須來自
        immutable snapshot，不可使用可變的目前欄位值。
        """
        from app.services.template_renderer import ExportResult, get_template_renderer

        fmt = (format or "").lower()
        if fmt not in self._EXPORT_FORMATS:
            raise WorkflowPersistenceError(f"unsupported export format: {format}")
        row = self.assert_form_exportable(
            tenant_id=tenant_id,
            instance_id=instance_id,
            actor_id=actor_id,
            actor_roles=actor_roles,
            is_superuser=is_superuser,
        )
        snapshot = dict(row.immutable_snapshot or {})
        approval_info = {
            "version": snapshot.get("schema_version") or row.form_version or "1.0",
            "approved_by": str(row.approved_by) if row.approved_by else "",
            "approved_at": row.approved_at.isoformat() if row.approved_at else "",
            "submitted_by": snapshot.get("submitted_by", ""),
            "submitted_at": snapshot.get("submitted_at", ""),
        }
        values = dict(snapshot.get("values") or {})
        form_key = snapshot.get("form_key") or ""
        if not form_key:
            try:
                form_key = self._form_definition_for_instance(tenant_id, row).form_key
            except Exception:
                form_key = "form"

        # 公司版型優先：DOCX/XLSX 套既有範本；缺依賴 fail-closed（不冒充通用兩欄表）
        result = None
        if fmt in {"docx", "xlsx", "pdf"}:
            try:
                from app.services.form_template_service import (
                    FormTemplateService,
                    convert_office_template_to_pdf,
                )

                tmpl = FormTemplateService(self.db).get_active(tenant_id, form_key)
                if tmpl is not None and tmpl.format == fmt:
                    content, filename, _media = FormTemplateService(self.db).preview(
                        tenant_id=tenant_id,
                        template_id=tmpl.id,
                        values=values,
                    )
                    result = ExportResult(
                        format=fmt,
                        content=content,
                        filename=filename,
                        metadata={"template_id": str(tmpl.id), "version": tmpl.version},
                    )
                elif tmpl is not None and fmt == "pdf":
                    content, _filename, _media = FormTemplateService(self.db).preview(
                        tenant_id=tenant_id,
                        template_id=tmpl.id,
                        values=values,
                    )
                    pdf = convert_office_template_to_pdf(content, tmpl.format, form_key)
                    result = ExportResult(
                        format="pdf",
                        content=pdf,
                        filename=f"{form_key}.pdf",
                        metadata={"template_id": str(tmpl.id), "version": tmpl.version},
                    )
                elif tmpl is not None:
                    result = ExportResult(
                        format=fmt,
                        error=(
                            f"active company template is {tmpl.format}; "
                            f"requested {fmt} — refuse generic fallback"
                        ),
                    )
            except Exception as exc:
                result = ExportResult(format=fmt, error=f"company template render failed: {exc}")

        if result is None:
            renderer = get_template_renderer()
            render = {
                "pdf": renderer.render_pdf,
                "docx": renderer.render_docx,
                "xlsx": renderer.render_excel,
                "md": renderer.render_markdown,
            }[fmt]
            # 若租戶有公司版型卻走到通用渲染，DOCX/XLSX 應已上面處理；
            # PDF 由核准版文件轉出（無轉檔依賴時 fail-closed）
            if result is None:
                result = render(
                    title=form_key,
                    fields=values,
                    provenance=dict(snapshot.get("provenance") or {}),
                    approval_info=approval_info,
                )
        if result.success:
            artifacts = list(row.export_artifacts or [])
            entry: Dict[str, Any] = {
                "format": result.format,
                "filename": result.filename,
                "exported_by": str(actor_id),
                "exported_at": _now().isoformat(),
            }
            if artifact_extra:
                entry.update(artifact_extra)
            artifacts.append(entry)
            row.export_artifacts = artifacts
            self.db.flush()
        return result

    def _form_definition_for_instance(
        self, tenant_id: UUID, instance: FormInstance
    ) -> FormDefinition:
        definition = (
            self.db.query(FormDefinition)
            .filter(
                FormDefinition.id == instance.form_definition_id,
                FormDefinition.tenant_id == tenant_id,
            )
            .first()
        )
        if definition is None:
            raise WorkflowNotFoundError("form definition not found for tenant")
        return definition

    def _check_form_mutable(self, row: FormInstance) -> None:
        if row.status not in self._FORM_MUTABLE_STATES:
            raise WorkflowConflictError(f"form is immutable while status={row.status}")

    def _get_form_instance(
        self, tenant_id: UUID, instance_id: UUID, *, for_update: bool = False
    ) -> FormInstance:
        query = self.db.query(FormInstance).filter(
            FormInstance.id == instance_id,
            FormInstance.tenant_id == tenant_id,
        )
        if for_update:
            query = query.with_for_update()
        row = query.first()
        if row is None:
            raise WorkflowNotFoundError("form instance not found")
        return row

    @staticmethod
    def _authorize_form_actor(
        row: FormInstance,
        *,
        actor_id: UUID,
        actor_roles: Iterable[str],
        is_superuser: bool,
    ) -> None:
        roles = set(actor_roles)
        if actor_id == row.owner_id or is_superuser or roles.intersection({"owner", "admin"}):
            return
        raise WorkflowForbiddenError("form access requires owner, admin, or superuser")

    # MKA approvals ---------------------------------------------------------
    def list_approvals(
        self, *, tenant_id: UUID, status: str = "pending", limit: int = 100
    ) -> List[WorkflowApprovalRequest]:
        query = self.db.query(WorkflowApprovalRequest).filter(
            WorkflowApprovalRequest.tenant_id == tenant_id
        )
        if status:
            query = query.filter(WorkflowApprovalRequest.status == status)
        return query.order_by(WorkflowApprovalRequest.created_at.desc()).limit(limit).all()

    def get_approval(
        self, *, tenant_id: UUID, approval_id: UUID
    ) -> WorkflowApprovalRequest:
        return self._get_approval(tenant_id, approval_id)

    def get_pending_approval_for_object(
        self, *, tenant_id: UUID, object_type: str, object_id: UUID
    ) -> WorkflowApprovalRequest:
        row = (
            self.db.query(WorkflowApprovalRequest)
            .filter(
                WorkflowApprovalRequest.tenant_id == tenant_id,
                WorkflowApprovalRequest.object_type == object_type,
                WorkflowApprovalRequest.object_id == object_id,
                WorkflowApprovalRequest.status == "pending",
            )
            .order_by(WorkflowApprovalRequest.created_at.desc())
            .first()
        )
        if row is None:
            raise WorkflowNotFoundError("pending approval request not found")
        return row

    def decide_approval(
        self,
        *,
        tenant_id: UUID,
        approval_id: UUID,
        reviewer_id: UUID,
        reviewer_roles: Iterable[str],
        expected_version: int,
        idempotency_key: str,
        action: str,
        reason: str = "",
        is_superuser: bool = False,
    ) -> WorkflowApprovalRequest:
        if action not in {"approve", "reject", "request_changes"}:
            raise WorkflowPersistenceError(f"unsupported approval action: {action}")
        if not idempotency_key.strip():
            raise WorkflowPersistenceError("decision idempotency_key is required")
        row = self._get_approval(tenant_id, approval_id, for_update=True)
        for decision in row.decision_log or []:
            if decision.get("idempotency_key") != idempotency_key:
                continue
            same_request = (
                decision.get("reviewer_id") == str(reviewer_id)
                and decision.get("action") == action
                and (decision.get("reason") or "") == reason
            )
            if same_request:
                return row
            raise WorkflowConflictError(
                "decision idempotency key was reused with different content"
            )
        self._check_version(row.record_version, expected_version)
        if row.status != "pending":
            raise WorkflowConflictError(f"approval is not pending: {row.status}")
        policy = self._approval_policy(
            tenant_id=tenant_id,
            policy_id=row.approval_policy_id,
            object_type=row.object_type,
        )
        required_roles = set(self._step_roles(policy, row.current_step))
        actual_roles = set(reviewer_roles)
        if not is_superuser:
            # fail-closed：政策步驟未配置角色時拒絕決審，而非跳過授權檢查
            if not required_roles:
                raise WorkflowForbiddenError(
                    "approval step has no reviewer roles configured"
                )
            if required_roles.isdisjoint(actual_roles):
                raise WorkflowForbiddenError(
                    "reviewer role not allowed for current approval step"
                )

        decided_step = row.current_step
        row.record_version += 1

        if action == "approve":
            steps = list(policy.steps or [])
            if row.current_step + 1 < max(len(steps), 1):
                row.current_step += 1
                row.reviewers = self._step_roles(policy, row.current_step)
            else:
                row.status = "approved"
                self._apply_approval(row, reviewer_id)
        elif action == "reject":
            row.status = "rejected"
            self._apply_rejection(row, reviewer_id, reason)
        else:
            row.status = "changes_requested"
            self._apply_changes_requested(row)
        log = list(row.decision_log or [])
        log.append(
            {
                "idempotency_key": idempotency_key,
                "step": decided_step,
                "action": action,
                "reviewer_id": str(reviewer_id),
                "reviewer_roles": sorted(actual_roles),
                "reason": reason,
                "decided_at": _now().isoformat(),
                "result_status": row.status,
                "result_step": row.current_step,
                "result_record_version": row.record_version,
            }
        )
        row.decision_log = log
        # Persist the business decision before looking up its optional task
        # workspace counterpart.  The lookup may issue SQL, and therefore
        # must not cause a premature/autoflush of the just-mutated form.
        self.db.flush()
        self._sync_task_run_for_approval(
            row,
            reviewer_id=reviewer_id,
            action=action,
            reason=reason,
        )
        self.db.flush()
        return row

    def _get_approval(
        self, tenant_id: UUID, approval_id: UUID, *, for_update: bool = False
    ) -> WorkflowApprovalRequest:
        query = self.db.query(WorkflowApprovalRequest).filter(
            WorkflowApprovalRequest.id == approval_id,
            WorkflowApprovalRequest.tenant_id == tenant_id,
        )
        if for_update:
            query = query.with_for_update()
        row = query.first()
        if row is None:
            raise WorkflowNotFoundError("approval request not found")
        return row

    def _apply_approval(
        self, approval: WorkflowApprovalRequest, reviewer_id: UUID
    ) -> None:
        if approval.object_type == "form":
            row = self._get_form_instance(
                approval.tenant_id, approval.object_id, for_update=True
            )
            row.status = "approved"
            row.approved_by = reviewer_id
            row.approved_at = _now()
            row.record_version += 1
        else:
            from app.composition.approval_objects import apply_application_approval

            apply_application_approval(
                self.db,
                approval,
                action="approve",
                reviewer_id=reviewer_id,
            )

    def _apply_rejection(
        self, approval: WorkflowApprovalRequest, reviewer_id: UUID, reason: str
    ) -> None:
        if approval.object_type == "form":
            row = self._get_form_instance(
                approval.tenant_id, approval.object_id, for_update=True
            )
            row.status = "rejected"
            row.approval_request_id = None
            row.immutable_snapshot = {}
            row.record_version += 1
        else:
            from app.composition.approval_objects import apply_application_approval

            apply_application_approval(
                self.db,
                approval,
                action="reject",
                reviewer_id=reviewer_id,
                reason=reason,
            )

    def _apply_changes_requested(self, approval: WorkflowApprovalRequest) -> None:
        if approval.object_type == "form":
            row = self._get_form_instance(
                approval.tenant_id, approval.object_id, for_update=True
            )
            row.status = "changes_requested"
            row.approval_request_id = None
            row.immutable_snapshot = {}
            row.record_version += 1
        else:
            from app.composition.approval_objects import apply_application_approval

            apply_application_approval(
                self.db,
                approval,
                action="request_changes",
                reviewer_id=None,
            )

    def _sync_task_run_for_approval(
        self,
        approval: WorkflowApprovalRequest,
        *,
        reviewer_id: UUID,
        action: str,
        reason: str,
    ) -> None:
        """Keep a task workspace aligned with the form/card it created.

        Task runs retain the user-facing workflow context, while approvals own
        the business decision.  Without this bridge a returned form left its
        task run at ``waiting_review`` forever, so the user could neither see
        the review feedback nor resume the same task.
        """
        if approval.status not in {"approved", "rejected", "changes_requested"}:
            return

        # The repository is also used by narrow persistence tests and legacy
        # installations that predate the task workspace tables.  A business
        # approval must still succeed there; only the optional workspace sync
        # is unavailable.
        # Inspect the session connection, rather than its Engine.  This is
        # essential for SQLite's StaticPool test setup: opening an Engine
        # connection there would share the DB-API connection and roll back the
        # current approval transaction when the inspector closes it.
        if "mka_task_runs" not in inspect(self.db.connection()).get_table_names():
            return

        from app.models.workflow import TaskRun, TaskRunEvent

        reference_key = "form_instance_id" if approval.object_type == "form" else None
        if reference_key is None:
            from app.composition.approval_objects import (
                application_approval_task_reference_key,
            )

            reference_key = application_approval_task_reference_key(
                approval.object_type
            )
        if reference_key is None:
            return

        target_status = "approved" if approval.status == "approved" else "rejected"
        object_id = str(approval.object_id)
        # JSON containment differs between PostgreSQL and SQLite.  Filtering
        # tenant-scoped rows in SQL and matching the small task reference in
        # Python keeps the behaviour portable for request handling and tests.
        candidates = self.db.query(TaskRun).filter(
            TaskRun.tenant_id == approval.tenant_id,
            TaskRun.status == "waiting_review",
        ).all()
        for run in candidates:
            if str((run.output_refs or {}).get(reference_key, "")) != object_id:
                continue

            from_status = run.status
            run.status = target_status
            refs = dict(run.output_refs or {})
            refs.update({
                "approval_id": str(approval.id),
                "approval_status": approval.status,
                "form_status": approval.status if approval.object_type == "form" else refs.get("form_status"),
            })
            run.output_refs = refs
            provenance = dict(run.provenance or {})
            provenance["review"] = {
                "approval_id": str(approval.id),
                "status": approval.status,
                "action": action,
                "reason": reason,
                "reviewer_id": str(reviewer_id),
                "decided_at": _now().isoformat(),
            }
            run.provenance = provenance
            self.db.add(TaskRunEvent(
                tenant_id=run.tenant_id,
                run_id=run.id,
                event_type="approval_decided",
                actor_id=reviewer_id,
                payload={
                    "approval_id": str(approval.id),
                    "action": action,
                    "approval_status": approval.status,
                    "from": from_status,
                    "to": target_status,
                    "reason": reason,
                },
            ))

    def _approval_policy(
        self,
        *,
        tenant_id: UUID,
        policy_id: Optional[UUID],
        object_type: str,
    ) -> ApprovalPolicy:
        query = self.db.query(ApprovalPolicy).filter(
            ApprovalPolicy.tenant_id == tenant_id,
            ApprovalPolicy.object_type == object_type,
            ApprovalPolicy.status == "active",
        )
        if policy_id:
            query = query.filter(ApprovalPolicy.id == policy_id)
        policy = query.order_by(ApprovalPolicy.created_at.desc()).first()
        if policy is None:
            module_key = None
            if object_type != "form":
                from app.composition.approval_objects import (
                    application_approval_module_key,
                )

                module_key = application_approval_module_key(object_type)
            policy = ApprovalPolicy(
                tenant_id=tenant_id,
                module_key=module_key,
                object_type=object_type,
                version="1.0",
                status="active",
                risk_level="medium",
                steps=[{"name": "review", "roles": ["owner", "admin"]}],
            )
            self.db.add(policy)
            self.db.flush()
        return policy

    @staticmethod
    def _step_roles(policy: ApprovalPolicy, step: int) -> List[str]:
        steps = list(policy.steps or [])
        if not steps:
            return ["owner", "admin"]
        if step >= len(steps):
            return []
        return list((steps[step] or {}).get("roles") or [])

    @staticmethod
    def _check_version(actual: int, expected: int) -> None:
        if actual != expected:
            raise WorkflowConflictError(
                f"stale record_version: expected {expected}, actual {actual}"
            )
