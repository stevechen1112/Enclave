"""Request-scoped persistence for the MKA domain.

Every read and write in this module carries an explicit tenant predicate.  The
repository intentionally accepts an existing SQLAlchemy ``Session``; callers
must use the request session and must not create process-wide DB sessions.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.mka import (
    ApprovalPolicy,
    FormDefinition,
    FormInstance,
    InteractionSession,
    KnowhowCardModel,
    MKAApprovalRequest,
)
from app.services.fixed_form import (
    FieldType,
    FixedFormCalculator,
    FixedFormSchema,
    FixedFormValidator,
    FormField,
    get_form_registry,
)


class MKAPersistenceError(ValueError):
    """Base exception translated to a safe HTTP response by MKA endpoints."""


class MKANotFoundError(MKAPersistenceError):
    pass


class MKAConflictError(MKAPersistenceError):
    pass


class MKAForbiddenError(MKAPersistenceError):
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
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "form_definition_id": str(row.form_definition_id),
        "form_version": row.form_version,
        "module_key": row.module_key,
        "owner_id": str(row.owner_id),
        "status": row.status,
        "record_version": row.record_version,
        "values": row.values_json or {},
        "provenance": row.provenance_json or {},
        "calculation_snapshot": row.calculation_snapshot or {},
        "validation_result": row.validation_result or {},
        "approval_request_id": str(row.approval_request_id) if row.approval_request_id else None,
        "immutable_snapshot": row.immutable_snapshot or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def interaction_to_dict(row: InteractionSession) -> Dict[str, Any]:
    return {
        "session_id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "user_id": str(row.user_id),
        "module_key": row.module_key,
        "channel": row.channel,
        "scene_context": row.scene_context or {},
        "transcript": row.transcript,
        "transcript_metadata": row.transcript_metadata or {},
        "transcript_confirmed_at": (
            row.transcript_confirmed_at.isoformat() if row.transcript_confirmed_at else None
        ),
        "detected_fields": row.detected_fields or {},
        "risk_level": row.risk_level,
        "state": row.state,
    }


def approval_to_dict(row: MKAApprovalRequest) -> Dict[str, Any]:
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


def knowhow_to_dict(row: KnowhowCardModel) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "card_id": row.card_id,
        "title": row.title,
        "summary": row.summary or "",
        "status": row.status,
        "authority_level": row.authority_level,
        "risk_level": row.risk_level,
        "applicable_roles": row.applicable_roles or [],
        "equipment_ids": row.equipment_ids or [],
        "product_ids": row.product_ids or [],
        "customer_ids": row.customer_ids or [],
        "problem_context": row.problem_context,
        "recommended_actions": row.recommended_actions or [],
        "steps": row.steps or [],
        "cautions": row.cautions or [],
        "source_quotes": row.source_quotes or [],
        "source_type": row.source_type,
        "source_document_id": row.source_document_id,
        "prerequisites": row.prerequisites or [],
        "risks": row.risks or [],
        "prohibited_actions": row.prohibited_actions or [],
        "related_sop_ids": row.related_sop_ids or [],
        "conflict_report": row.conflict_report or [],
        "version": row.version,
        "reviewer": str(row.reviewer) if row.reviewer else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "retired_at": row.retired_at.isoformat() if row.retired_at else None,
    }


class MKARepository:
    """Tenant-scoped MKA repository backed by the caller's DB session."""

    _FORM_MUTABLE_STATES = {"draft", "changes_requested", "rejected"}
    _KNOWHOW_MUTABLE_STATES = {"draft", "changes_requested", "rejected"}

    def __init__(self, db: Session):
        self.db = db

    # Voice -----------------------------------------------------------------
    def save_transcript(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        text: str,
        metadata: Dict[str, Any],
        detected_fields: Sequence[Dict[str, Any]],
        session_id: Optional[UUID] = None,
        module_key: Optional[str] = None,
        channel: str = "web",
        scene_context: Optional[Dict[str, Any]] = None,
        risk_level: str = "low",
    ) -> InteractionSession:
        row: Optional[InteractionSession] = None
        if session_id:
            row = (
                self.db.query(InteractionSession)
                .filter(
                    InteractionSession.id == session_id,
                    InteractionSession.tenant_id == tenant_id,
                    InteractionSession.user_id == user_id,
                )
                .first()
            )
            if row is None:
                raise MKANotFoundError("interaction session not found")
            if row.state in {"completed", "expired"}:
                raise MKAConflictError(f"interaction session is {row.state}")
        if row is None:
            row = InteractionSession(
                tenant_id=tenant_id,
                user_id=user_id,
                module_key=module_key,
                channel=channel,
            )
            self.db.add(row)
        row.transcript = text
        row.transcript_metadata = _copy_json(metadata)
        row.detected_fields = {"fields": _copy_json(list(detected_fields))}
        row.scene_context = _copy_json(scene_context or {})
        row.risk_level = risk_level
        row.transcript_confirmed_at = None
        row.state = "waiting_confirmation"
        self.db.flush()
        return row

    def confirm_transcript(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        session_id: UUID,
        confirmed_text: Optional[str] = None,
        confirmed_fields: Optional[Dict[str, Any]] = None,
    ) -> InteractionSession:
        row = self._interaction(tenant_id, user_id, session_id)
        if row.state in {"completed", "expired"}:
            raise MKAConflictError(f"interaction session is {row.state}")
        if confirmed_text is not None:
            metadata = dict(row.transcript_metadata or {})
            metadata["draft_transcript"] = row.transcript
            row.transcript_metadata = metadata
            row.transcript = confirmed_text
        detected = dict(row.detected_fields or {})
        fields = []
        confirmed_fields = confirmed_fields or {}
        for item in detected.get("fields", []):
            field = dict(item)
            key = field.get("type")
            if key in confirmed_fields:
                field["confirmed_value"] = confirmed_fields[key]
            field["needs_confirm"] = False
            fields.append(field)
        row.detected_fields = {"fields": fields}
        row.transcript_confirmed_at = _now()
        row.state = "active"
        self.db.flush()
        return row

    def resolve_interaction(
        self, *, tenant_id: UUID, user_id: UUID, session_id: UUID
    ) -> InteractionSession:
        row = self._interaction(tenant_id, user_id, session_id)
        if row.risk_level == "high" and row.transcript_confirmed_at is None:
            raise MKAConflictError("high-risk transcript must be confirmed before resolve")
        row.state = "completed"
        self.db.flush()
        return row

    def _interaction(
        self, tenant_id: UUID, user_id: UUID, session_id: UUID
    ) -> InteractionSession:
        row = (
            self.db.query(InteractionSession)
            .filter(
                InteractionSession.id == session_id,
                InteractionSession.tenant_id == tenant_id,
                InteractionSession.user_id == user_id,
            )
            .first()
        )
        if row is None:
            raise MKANotFoundError("interaction session not found")
        return row

    # Fixed forms -----------------------------------------------------------
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
            raise MKANotFoundError(f"form definition not found: {form_key}")
        return row

    def create_form_instance(
        self,
        *,
        tenant_id: UUID,
        owner_id: UUID,
        form_key: str,
        values: Optional[Dict[str, Any]] = None,
        provenance: Optional[Dict[str, Any]] = None,
        module_key: Optional[str] = None,
    ) -> FormInstance:
        definition = self.get_form_definition(tenant_id=tenant_id, form_key=form_key)
        schema = _schema_from_definition(definition)
        initial = {
            field.name: field.default
            for field in schema.fields
            if field.default is not None
        }
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
    ) -> tuple[FormInstance, MKAApprovalRequest]:
        row = self._get_form_instance(tenant_id, instance_id, for_update=True)
        if submitted_by != row.owner_id:
            raise MKAForbiddenError("only the form owner may submit this form")
        existing = (
            self.db.query(MKAApprovalRequest)
            .filter(
                MKAApprovalRequest.tenant_id == tenant_id,
                MKAApprovalRequest.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing is not None:
            if existing.object_type != "form" or existing.object_id != instance_id:
                raise MKAConflictError("idempotency key belongs to another object")
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
            raise MKAConflictError("form validation failed: " + "; ".join(errors))

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
        approval = MKAApprovalRequest(
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
            raise MKANotFoundError("form definition not found for tenant")
        return definition

    def _check_form_mutable(self, row: FormInstance) -> None:
        if row.status not in self._FORM_MUTABLE_STATES:
            raise MKAConflictError(f"form is immutable while status={row.status}")

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
            raise MKANotFoundError("form instance not found")
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
        raise MKAForbiddenError("form access requires owner, admin, or superuser")

    # MKA approvals ---------------------------------------------------------
    def list_approvals(
        self, *, tenant_id: UUID, status: str = "pending"
    ) -> List[MKAApprovalRequest]:
        query = self.db.query(MKAApprovalRequest).filter(
            MKAApprovalRequest.tenant_id == tenant_id
        )
        if status:
            query = query.filter(MKAApprovalRequest.status == status)
        return query.order_by(MKAApprovalRequest.created_at.desc()).limit(100).all()

    def get_approval(
        self, *, tenant_id: UUID, approval_id: UUID
    ) -> MKAApprovalRequest:
        return self._get_approval(tenant_id, approval_id)

    def get_pending_approval_for_object(
        self, *, tenant_id: UUID, object_type: str, object_id: UUID
    ) -> MKAApprovalRequest:
        row = (
            self.db.query(MKAApprovalRequest)
            .filter(
                MKAApprovalRequest.tenant_id == tenant_id,
                MKAApprovalRequest.object_type == object_type,
                MKAApprovalRequest.object_id == object_id,
                MKAApprovalRequest.status == "pending",
            )
            .order_by(MKAApprovalRequest.created_at.desc())
            .first()
        )
        if row is None:
            raise MKANotFoundError("pending approval request not found")
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
    ) -> MKAApprovalRequest:
        if action not in {"approve", "reject", "request_changes"}:
            raise MKAPersistenceError(f"unsupported approval action: {action}")
        if not idempotency_key.strip():
            raise MKAPersistenceError("decision idempotency_key is required")
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
            raise MKAConflictError(
                "decision idempotency key was reused with different content"
            )
        self._check_version(row.record_version, expected_version)
        if row.status != "pending":
            raise MKAConflictError(f"approval is not pending: {row.status}")
        policy = self._approval_policy(
            tenant_id=tenant_id,
            policy_id=row.approval_policy_id,
            object_type=row.object_type,
        )
        required_roles = set(self._step_roles(policy, row.current_step))
        actual_roles = set(reviewer_roles)
        if not is_superuser and required_roles and required_roles.isdisjoint(actual_roles):
            raise MKAForbiddenError(
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
        self.db.flush()
        return row

    def _get_approval(
        self, tenant_id: UUID, approval_id: UUID, *, for_update: bool = False
    ) -> MKAApprovalRequest:
        query = self.db.query(MKAApprovalRequest).filter(
            MKAApprovalRequest.id == approval_id,
            MKAApprovalRequest.tenant_id == tenant_id,
        )
        if for_update:
            query = query.with_for_update()
        row = query.first()
        if row is None:
            raise MKANotFoundError("approval request not found")
        return row

    def _apply_approval(
        self, approval: MKAApprovalRequest, reviewer_id: UUID
    ) -> None:
        if approval.object_type == "form":
            row = self._get_form_instance(
                approval.tenant_id, approval.object_id, for_update=True
            )
            row.status = "approved"
            row.approved_by = reviewer_id
            row.approved_at = _now()
            row.record_version += 1
        elif approval.object_type == "knowhow":
            row = self.get_knowhow(
                tenant_id=approval.tenant_id, knowhow_id=approval.object_id
            )
            row.status = "approved"
            row.reviewer = reviewer_id
            row.reviewed_at = _now()
            row.effective_from = row.effective_from or _now()

    def _apply_rejection(
        self, approval: MKAApprovalRequest, reviewer_id: UUID, reason: str
    ) -> None:
        if approval.object_type == "form":
            row = self._get_form_instance(
                approval.tenant_id, approval.object_id, for_update=True
            )
            row.status = "rejected"
            row.approval_request_id = None
            row.immutable_snapshot = {}
            row.record_version += 1
        elif approval.object_type == "knowhow":
            row = self.get_knowhow(
                tenant_id=approval.tenant_id, knowhow_id=approval.object_id
            )
            row.status = "rejected"
            row.reviewer = reviewer_id
            row.reviewed_at = _now()
            row.rejection_reason = reason

    def _apply_changes_requested(self, approval: MKAApprovalRequest) -> None:
        if approval.object_type == "form":
            row = self._get_form_instance(
                approval.tenant_id, approval.object_id, for_update=True
            )
            row.status = "changes_requested"
            row.approval_request_id = None
            row.immutable_snapshot = {}
            row.record_version += 1
        elif approval.object_type == "knowhow":
            row = self.get_knowhow(
                tenant_id=approval.tenant_id, knowhow_id=approval.object_id
            )
            row.status = "changes_requested"

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
            policy = ApprovalPolicy(
                tenant_id=tenant_id,
                module_key="training_knowhow" if object_type == "knowhow" else "fixed_form",
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

    # Know-how --------------------------------------------------------------
    def create_knowhow(
        self,
        *,
        tenant_id: UUID,
        title: str,
        summary: str = "",
        steps: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> KnowhowCardModel:
        data = dict(data or {})
        row = KnowhowCardModel(
            tenant_id=tenant_id,
            card_id=data.pop("card_id", str(uuid.uuid4())),
            title=title,
            summary=summary,
            steps=_copy_json(steps or []),
            status="draft",
            version=1,
            **self._knowhow_fields(data),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def list_knowhow(
        self,
        *,
        tenant_id: UUID,
        status: Optional[str] = None,
    ) -> List[KnowhowCardModel]:
        query = self.db.query(KnowhowCardModel).filter(
            KnowhowCardModel.tenant_id == tenant_id
        )
        if status:
            query = query.filter(KnowhowCardModel.status == status)
        return query.order_by(KnowhowCardModel.created_at.desc()).all()

    def list_approved_knowhow(
        self, *, tenant_id: UUID
    ) -> List[KnowhowCardModel]:
        return (
            self.db.query(KnowhowCardModel)
            .filter(
                KnowhowCardModel.tenant_id == tenant_id,
                KnowhowCardModel.status == "approved",
            )
            .order_by(KnowhowCardModel.updated_at.desc())
            .all()
        )

    def get_knowhow(
        self, *, tenant_id: UUID, knowhow_id: UUID
    ) -> KnowhowCardModel:
        row = (
            self.db.query(KnowhowCardModel)
            .filter(
                KnowhowCardModel.id == knowhow_id,
                KnowhowCardModel.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            raise MKANotFoundError("know-how card not found")
        return row

    def update_knowhow(
        self,
        *,
        tenant_id: UUID,
        knowhow_id: UUID,
        expected_version: int,
        data: Dict[str, Any],
    ) -> KnowhowCardModel:
        row = self.get_knowhow(tenant_id=tenant_id, knowhow_id=knowhow_id)
        if row.status not in self._KNOWHOW_MUTABLE_STATES:
            raise MKAConflictError(f"know-how is immutable while status={row.status}")
        self._check_version(row.version, expected_version)
        allowed = self._knowhow_fields(data)
        for key, value in allowed.items():
            setattr(row, key, _copy_json(value) if isinstance(value, (dict, list)) else value)
        if "title" in data:
            row.title = str(data["title"])
        if "summary" in data:
            row.summary = str(data["summary"])
        row.status = "draft"
        row.version += 1
        self.db.flush()
        return row

    def submit_knowhow(
        self,
        *,
        tenant_id: UUID,
        knowhow_id: UUID,
        submitted_by: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[KnowhowCardModel, MKAApprovalRequest]:
        existing = (
            self.db.query(MKAApprovalRequest)
            .filter(
                MKAApprovalRequest.tenant_id == tenant_id,
                MKAApprovalRequest.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing is not None:
            if existing.object_type != "knowhow" or existing.object_id != knowhow_id:
                raise MKAConflictError("idempotency key belongs to another object")
            return self.get_knowhow(tenant_id=tenant_id, knowhow_id=knowhow_id), existing

        row = self.get_knowhow(tenant_id=tenant_id, knowhow_id=knowhow_id)
        if row.status not in self._KNOWHOW_MUTABLE_STATES:
            raise MKAConflictError(f"cannot submit know-how from {row.status}")
        self._check_version(row.version, expected_version)
        unresolved = [
            item for item in (row.conflict_report or []) if not item.get("resolved")
        ]
        if unresolved:
            raise MKAConflictError(
                f"know-how has {len(unresolved)} unresolved SOP conflicts"
            )
        snapshot = _copy_json(knowhow_to_dict(row))
        policy = self._approval_policy(
            tenant_id=tenant_id, policy_id=None, object_type="knowhow"
        )
        approval = MKAApprovalRequest(
            tenant_id=tenant_id,
            approval_policy_id=policy.id,
            object_type="knowhow",
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
        row.status = "pending_review"
        self.db.flush()
        return row, approval

    def retire_knowhow(
        self, *, tenant_id: UUID, knowhow_id: UUID
    ) -> KnowhowCardModel:
        row = self.get_knowhow(tenant_id=tenant_id, knowhow_id=knowhow_id)
        if row.status == "retired":
            return row
        if row.status != "approved":
            raise MKAConflictError("only approved know-how can be retired")
        row.status = "retired"
        row.retired_at = _now()
        self.db.flush()
        return row

    @staticmethod
    def _knowhow_fields(data: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {
            "authority_level",
            "risk_level",
            "applicable_roles",
            "equipment_ids",
            "product_ids",
            "customer_ids",
            "problem_context",
            "recommended_actions",
            "steps",
            "cautions",
            "source_quotes",
            "source_type",
            "source_document_id",
            "prerequisites",
            "risks",
            "prohibited_actions",
            "source_audio_uri",
            "transcript_id",
            "interviewee",
            "interviewer",
            "related_sop_ids",
            "conflict_report",
            "effective_from",
            "expires_at",
        }
        return {key: value for key, value in data.items() if key in allowed}

    @staticmethod
    def _check_version(actual: int, expected: int) -> None:
        if actual != expected:
            raise MKAConflictError(
                f"stale record_version: expected {expected}, current {actual}"
            )

