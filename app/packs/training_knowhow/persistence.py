"""Training/know-how application persistence.

Every read and write in this module carries an explicit tenant predicate.  The
repository intentionally accepts an existing SQLAlchemy ``Session``; callers
must use the request session and must not create process-wide DB sessions.
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

logger = logging.getLogger(__name__)

from app.models.mka import KnowhowCardModel
from app.models.workflow import (
    ApprovalPolicy,
    FormDefinition,
    FormInstance,
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
from app.services.workflow_repository import (
    WorkflowConflictError,
    WorkflowForbiddenError,
    WorkflowNotFoundError,
    WorkflowPersistenceError,
    WorkflowRepository,
)


MKAPersistenceError = WorkflowPersistenceError
MKANotFoundError = WorkflowNotFoundError
MKAConflictError = WorkflowConflictError
MKAForbiddenError = WorkflowForbiddenError


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
        "owner_id": str(row.owner_id) if row.owner_id else None,
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


class MKARepository(WorkflowRepository):
    """Tenant-scoped MKA repository backed by the caller's DB session."""

    _FORM_MUTABLE_STATES = {"draft", "changes_requested", "rejected"}
    _KNOWHOW_MUTABLE_STATES = {"draft", "changes_requested", "rejected"}

    def __init__(self, db: Session):
        self.db = db

    # Know-how --------------------------------------------------------------
    def create_knowhow(
        self,
        *,
        tenant_id: UUID,
        title: str,
        summary: str = "",
        steps: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None,
        owner_id: Optional[UUID] = None,
    ) -> KnowhowCardModel:
        data = dict(data or {})
        row = KnowhowCardModel(
            tenant_id=tenant_id,
            owner_id=owner_id,
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

    @staticmethod
    def _check_knowhow_owner(
        row: KnowhowCardModel,
        *,
        actor_id: Optional[UUID],
        actor_roles: Iterable[str] = (),
        is_superuser: bool = False,
    ) -> None:
        """PATCH／submit 授權：僅卡片擁有者或 owner/admin/superuser 可修改。

        無 owner_id 的既有卡片 fail-closed：API 路徑（必帶 actor）下僅管理員可動。
        """
        if is_superuser:
            return
        if set(actor_roles or ()) & {"owner", "admin"}:
            return
        if row.owner_id is not None and actor_id is not None and row.owner_id == actor_id:
            return
        if row.owner_id is None and actor_id is None:
            return  # 舊有 repo 呼叫（未傳 actor）且卡片無主：維持相容
        raise MKAForbiddenError(
            "only the card owner or an admin can modify this know-how card"
        )

    def list_knowhow(
        self,
        *,
        tenant_id: UUID,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[KnowhowCardModel]:
        query = self.db.query(KnowhowCardModel).filter(
            KnowhowCardModel.tenant_id == tenant_id
        )
        if status:
            query = query.filter(KnowhowCardModel.status == status)
        return query.order_by(KnowhowCardModel.created_at.desc()).limit(limit).all()

    def list_approved_knowhow(
        self, *, tenant_id: UUID, limit: int = 500
    ) -> List[KnowhowCardModel]:
        # 檢索熱路徑使用：只有已核准、已生效、未到期且未逾複查日的
        # 卡片可進一般回答。review_due_at 為 NULL 代表核准時未設定定期複查。
        # reviewer/reviewed_at 是可稽核核准鏈，不能只相信 status 字串。
        from sqlalchemy import or_, func

        return (
            self.db.query(KnowhowCardModel)
            .filter(
                KnowhowCardModel.tenant_id == tenant_id,
                KnowhowCardModel.status == "approved",
                KnowhowCardModel.reviewer.isnot(None),
                KnowhowCardModel.reviewed_at.isnot(None),
                or_(KnowhowCardModel.effective_from.is_(None), KnowhowCardModel.effective_from <= func.now()),
                or_(KnowhowCardModel.expires_at.is_(None), KnowhowCardModel.expires_at > func.now()),
                or_(KnowhowCardModel.review_due_at.is_(None), KnowhowCardModel.review_due_at > func.now()),
            )
            .order_by(
                KnowhowCardModel.updated_at.desc(),
                KnowhowCardModel.id.desc(),
            )
            .limit(limit)
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
        actor_id: Optional[UUID] = None,
        actor_roles: Iterable[str] = (),
        is_superuser: bool = False,
    ) -> KnowhowCardModel:
        row = self.get_knowhow(tenant_id=tenant_id, knowhow_id=knowhow_id)
        self._check_knowhow_owner(
            row, actor_id=actor_id, actor_roles=actor_roles, is_superuser=is_superuser
        )
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
        actor_roles: Iterable[str] = (),
        is_superuser: bool = False,
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
        self._check_knowhow_owner(
            row, actor_id=submitted_by, actor_roles=actor_roles, is_superuser=is_superuser
        )
        if row.status not in self._KNOWHOW_MUTABLE_STATES:
            raise MKAConflictError(f"cannot submit know-how from {row.status}")
        self._check_version(row.version, expected_version)

        # ── SOP conflict detection (MKA-P5-CONFLICT) — 真實 Document 查詢 ──
        self._run_sop_conflict_check(row)

        unresolved = [
            item for item in (row.conflict_report or []) if not item.get("resolved")
        ]
        if unresolved:
            err = MKAConflictError(
                f"know-how has {len(unresolved)} unresolved SOP conflicts; "
                "resolve in UI before submit"
            )
            # 端點 rollback 會連 conflict_report 一起洗掉；隨例外帶出，
            # 讓端點能用新交易把報告存回去，UI 才看得到待處置衝突
            err.conflict_report = row.conflict_report or []  # type: ignore[attr-defined]
            raise err
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

    def _run_sop_conflict_check(self, row: KnowhowCardModel) -> None:
        """Run SOP conflict detection against real Document / Chunk content.

        衝突不得自動掩蓋：寫入 conflict_report，resolved=False，由 UI 顯示差異與處置。
        """
        from app.models.document import Document, DocumentChunk
        from app.services.sop_conflict import SOPConflictChecker

        checker = SOPConflictChecker()
        sop_docs: List[Dict[str, Any]] = []

        doc_ids = list(row.related_sop_ids or [])
        query = self.db.query(Document).filter(Document.tenant_id == row.tenant_id)
        if doc_ids:
            # related_sop_ids 可能是 UUID 字串或檔名
            from sqlalchemy import or_
            clauses = []
            for sid in doc_ids:
                try:
                    clauses.append(Document.id == UUID(str(sid)))
                except Exception:
                    clauses.append(Document.filename.ilike(f"%{sid}%"))
            if clauses:
                query = query.filter(or_(*clauses))
        else:
            from sqlalchemy import or_
            # 依設備／標題關鍵字找 SOP
            query = query.filter(
                or_(
                    Document.filename.ilike("%SOP%"),
                    Document.filename.ilike("%sop%"),
                    Document.filename.ilike("%作業標準%"),
                )
            )
            if row.equipment_ids:
                eq = str((row.equipment_ids or [None])[0] or "")
                if eq:
                    # 設備個體號（EQ-100-01）與機型（EQ-100）都可能是文件名稱的一部分；
                    # 僅用完整個體號會漏掉以機型命名的 SOP（如 D02_EQ-100_...SOP.md）
                    import re as _re
                    candidates = [eq]
                    model = _re.sub(r"-\d+$", "", eq)
                    if model and model != eq:
                        candidates.append(model)
                    query = query.filter(
                        or_(*[Document.filename.ilike(f"%{c}%") for c in candidates])
                    )

        documents = query.limit(10).all()
        for doc in documents:
            chunks = (
                self.db.query(DocumentChunk)
                .filter(
                    DocumentChunk.document_id == doc.id,
                    DocumentChunk.tenant_id == row.tenant_id,
                )
                .order_by(DocumentChunk.chunk_index.asc())
                .limit(40)
                .all()
            )
            texts = [c.text or "" for c in chunks if c.text]
            steps = [t for t in texts if any(k in t for k in ("步驟", "1.", "2.", "操作"))]
            cautions = [t for t in texts if any(k in t for k in ("注意", "禁止", "危險", "安全"))]
            sop_docs.append({
                "id": str(doc.id),
                "title": doc.filename or str(doc.id),
                "steps": steps or texts[:5],
                "applicable_equipment": list(row.equipment_ids or []),
                "cautions": cautions,
            })

        if not sop_docs:
            return

        conflicts = checker.check_conflicts(row, sop_docs)
        if not conflicts:
            row.conflict_report = []
            return

        # 不自動 resolve — 正式 SOP 優先，但必須人工確認差異。
        # 已處置過的衝突（同一衝突鍵）保留 resolved/resolution，
        # 否則使用者在 UI 標記處置後送審會被重跑偵測重置回未解決，永遠卡住。
        def _conflict_key(d: Dict[str, Any]) -> tuple:
            return (
                str(d.get("conflict_type") or ""),
                str(d.get("sop_field") or ""),
                str(d.get("sop_value") or "")[:80],
                str(d.get("knowhow_value") or "")[:80],
            )
        prior = {
            _conflict_key(item): item
            for item in (row.conflict_report or [])
            if isinstance(item, dict)
        }
        report = []
        for c in conflicts:
            d = c.to_dict()
            existing = prior.get(_conflict_key(d))
            if existing and existing.get("resolved"):
                d["resolved"] = True
                d["resolution"] = existing.get("resolution") or "manual"
            else:
                d["resolved"] = False
                d["resolution"] = ""
            d["preferred"] = "sop"
            report.append(d)
        row.conflict_report = report
        logger.info(
            "SOP conflict check for knowhow %s: %s conflicts (%s unresolved)",
            row.card_id,
            len(report),
            sum(1 for item in report if not item.get("resolved")),
        )

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
