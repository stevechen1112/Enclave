"""Input I8 tenant pilot evidence and acceptance API."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import require_admin
from app.models.input_pilot import (
    InputPilot,
    InputPilotAcceptance,
    InputPilotAudit,
    InputPilotDailyMetric,
    InputPilotIncident,
)
from app.models.user import User
from app.services.input_pilot import (
    DEFAULT_ACCEPTANCE,
    evaluate_pilot_gate,
    validate_pilot_configuration,
)

router = APIRouter(prefix="/operations/input/pilots", tags=["input-pilots"])
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _require_sha256(value: str) -> str:
    if not _SHA256.fullmatch(value):
        raise HTTPException(status_code=422, detail="evidence SHA-256 格式錯誤")
    return value.lower()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _require_running_pilot(pilot: InputPilot) -> None:
    if pilot.status != "running" or pilot.started_at is None:
        raise HTTPException(status_code=409, detail="Pilot 必須先啟動且仍在執行中")


class PilotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    evidence_mode: Literal["live", "synthetic"] = "live"
    dedicated_environment: bool
    environment_evidence_sha256: str = Field(min_length=64, max_length=64)
    data_processing_agreement_ref: str = Field(min_length=1, max_length=1000)
    journeys: list[dict[str, Any]] = Field(min_length=2, max_length=3)
    acceptance_config: dict[str, Any] = Field(default_factory=dict)


class DailyMetricIn(BaseModel):
    metric_date: date
    journey_key: str = Field(min_length=1, max_length=50)
    total_attempts: int = Field(ge=0)
    successful_attempts: int = Field(ge=0)
    retry_count: int = Field(default=0, ge=0)
    manual_correction_count: int = Field(default=0, ge=0)
    processing_p95_ms: int = Field(ge=0)
    retrieval_checks: int = Field(default=0, ge=0)
    cited_retrievals: int = Field(default=0, ge=0)
    friction_count: int = Field(default=0, ge=0)
    source_evidence_sha256: str = Field(min_length=64, max_length=64)
    notes: str | None = None


class IncidentIn(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    category: str = Field(min_length=1, max_length=32)
    near_miss: bool = False
    data_loss: bool = False
    unauthorized_access: bool = False
    false_completion: bool = False
    summary: str = Field(min_length=1)
    occurred_at: datetime


class IncidentResolve(BaseModel):
    root_cause: str = Field(min_length=1)
    corrective_action: str = Field(min_length=1)
    retrospective_sha256: str = Field(min_length=64, max_length=64)


class AuditIn(BaseModel):
    audit_type: Literal["quality", "security", "permission"]
    status: Literal["pending", "pass", "fail"]
    sample_size: int = Field(ge=0)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    evidence_sha256: str = Field(min_length=64, max_length=64)
    audited_at: datetime


class AcceptanceIn(BaseModel):
    decision: Literal["accepted", "rejected"]
    signer_name: str = Field(min_length=1, max_length=200)
    signer_role: str = Field(min_length=1, max_length=200)
    signed_document_sha256: str = Field(min_length=64, max_length=64)
    signed_document_ref: str = Field(min_length=1, max_length=1000)
    statement: str = Field(min_length=1)
    signed_at: datetime


class PilotRetrospectiveIn(BaseModel):
    retrospective_sha256: str = Field(min_length=64, max_length=64)
    retrospective_ref: str = Field(min_length=1, max_length=1000)


def _pilot(db: Session, tenant_id: UUID, pilot_id: UUID, *, lock: bool = False) -> InputPilot:
    query = db.query(InputPilot).filter(
        InputPilot.tenant_id == tenant_id,
        InputPilot.id == pilot_id,
    )
    row = query.with_for_update().first() if lock else query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Pilot 不存在")
    return row


@router.get("")
def list_pilots(
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> list[dict[str, Any]]:
    rows = db.query(InputPilot).filter(
        InputPilot.tenant_id == current_user.tenant_id
    ).order_by(InputPilot.created_at.desc()).all()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "status": row.status,
            "evidence_mode": row.evidence_mode,
            "journeys": row.journeys or [],
            "started_at": row.started_at,
            "planned_end_at": row.planned_end_at,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("")
def create_pilot(
    payload: PilotCreate,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    pilot = InputPilot(
        tenant_id=current_user.tenant_id,
        name=payload.name,
        evidence_mode=payload.evidence_mode,
        dedicated_environment=payload.dedicated_environment,
        environment_evidence_sha256=_require_sha256(payload.environment_evidence_sha256),
        data_processing_agreement_ref=payload.data_processing_agreement_ref,
        journeys=payload.journeys,
        acceptance_config={**DEFAULT_ACCEPTANCE, **payload.acceptance_config},
        created_by=current_user.id,
    )
    errors = validate_pilot_configuration(pilot)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    owner_ids: set[UUID] = set()
    for journey in payload.journeys:
        try:
            owner_ids.add(UUID(str(journey.get("review_owner_id"))))
        except (TypeError, ValueError, AttributeError) as exc:
            raise HTTPException(status_code=422, detail="review_owner_id 格式錯誤") from exc
    valid_owners = db.query(User).filter(
        User.tenant_id == current_user.tenant_id,
        User.id.in_(owner_ids),
        User.status == "active",
    ).count()
    if valid_owners != len(owner_ids):
        raise HTTPException(status_code=422, detail="review owner 必須是本租戶有效使用者")
    pilot.status = "ready"
    db.add(pilot)
    db.commit()
    return {"id": str(pilot.id), "status": pilot.status}


@router.post("/{pilot_id}/start")
def start_pilot(
    pilot_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    pilot = _pilot(db, current_user.tenant_id, pilot_id, lock=True)
    errors = validate_pilot_configuration(pilot)
    if errors:
        raise HTTPException(status_code=409, detail={"errors": errors})
    if pilot.status != "ready":
        raise HTTPException(status_code=409, detail="Pilot 狀態不可啟動")
    pilot.status = "running"
    pilot.started_at = datetime.now(timezone.utc)
    pilot.planned_end_at = pilot.started_at + timedelta(
        days=int((pilot.acceptance_config or DEFAULT_ACCEPTANCE)["minimum_days"]) - 1
    )
    db.commit()
    return {"id": str(pilot.id), "status": pilot.status, "started_at": pilot.started_at}


@router.post("/{pilot_id}/daily-metrics")
def record_daily_metric(
    pilot_id: UUID,
    payload: DailyMetricIn,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    pilot = _pilot(db, current_user.tenant_id, pilot_id)
    _require_running_pilot(pilot)
    keys = {item.get("key") for item in (pilot.journeys or [])}
    if payload.journey_key not in keys:
        raise HTTPException(status_code=422, detail="journey 不在 Pilot 設定中")
    if payload.successful_attempts > payload.total_attempts:
        raise HTTPException(status_code=422, detail="successful_attempts 超過 total_attempts")
    if payload.cited_retrievals > payload.retrieval_checks:
        raise HTTPException(status_code=422, detail="cited_retrievals 超過 retrieval_checks")
    today = datetime.now(timezone.utc).date()
    started_date = _as_utc(pilot.started_at).date()
    maximum_days = int((pilot.acceptance_config or DEFAULT_ACCEPTANCE)["maximum_days"])
    if payload.metric_date < started_date or payload.metric_date > today:
        raise HTTPException(status_code=422, detail="metric_date 必須介於 Pilot 開始日與今天")
    if (payload.metric_date - started_date).days >= maximum_days:
        raise HTTPException(status_code=422, detail="metric_date 超過 Pilot 最大觀察期間")
    row = InputPilotDailyMetric(
        tenant_id=current_user.tenant_id,
        pilot_id=pilot.id,
        **{
            **payload.model_dump(),
            "source_evidence_sha256": _require_sha256(payload.source_evidence_sha256),
        },
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="該日 journey 指標已存在；證據不可覆寫") from exc
    return {"id": str(row.id), "status": "recorded"}


@router.post("/{pilot_id}/incidents")
def record_incident(
    pilot_id: UUID,
    payload: IncidentIn,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    pilot = _pilot(db, current_user.tenant_id, pilot_id)
    _require_running_pilot(pilot)
    occurred_at = _as_utc(payload.occurred_at)
    if occurred_at < _as_utc(pilot.started_at) or occurred_at > datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="occurred_at 必須介於 Pilot 開始時間與現在")
    row = InputPilotIncident(
        tenant_id=current_user.tenant_id,
        pilot_id=pilot.id,
        **payload.model_dump(),
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/{pilot_id}/incidents/{incident_id}/resolve")
def resolve_incident(
    pilot_id: UUID,
    incident_id: UUID,
    payload: IncidentResolve,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    _pilot(db, current_user.tenant_id, pilot_id)
    row = db.query(InputPilotIncident).filter(
        InputPilotIncident.tenant_id == current_user.tenant_id,
        InputPilotIncident.pilot_id == pilot_id,
        InputPilotIncident.id == incident_id,
    ).with_for_update().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Incident 不存在")
    row.status = "resolved"
    row.root_cause = payload.root_cause
    row.corrective_action = payload.corrective_action
    row.retrospective_sha256 = _require_sha256(payload.retrospective_sha256)
    row.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/{pilot_id}/audits")
def record_audit(
    pilot_id: UUID,
    payload: AuditIn,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    pilot = _pilot(db, current_user.tenant_id, pilot_id)
    _require_running_pilot(pilot)
    audited_at = _as_utc(payload.audited_at)
    if audited_at < _as_utc(pilot.started_at) or audited_at > datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="audited_at 必須介於 Pilot 開始時間與現在")
    if payload.status == "pass" and payload.sample_size <= 0:
        raise HTTPException(status_code=422, detail="通過的 audit 必須有抽樣資料")
    row = InputPilotAudit(
        tenant_id=current_user.tenant_id,
        pilot_id=pilot.id,
        auditor_id=current_user.id,
        **{
            **payload.model_dump(),
            "evidence_sha256": _require_sha256(payload.evidence_sha256),
        },
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/{pilot_id}/retrospective")
def record_pilot_retrospective(
    pilot_id: UUID,
    payload: PilotRetrospectiveIn,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    pilot = _pilot(db, current_user.tenant_id, pilot_id, lock=True)
    _require_running_pilot(pilot)
    if pilot.retrospective_sha256:
        raise HTTPException(status_code=409, detail="Pilot retrospective 已存在且不可覆寫")
    pilot.retrospective_sha256 = _require_sha256(payload.retrospective_sha256)
    pilot.retrospective_ref = payload.retrospective_ref
    db.commit()
    return {"id": str(pilot.id), "status": "recorded"}


@router.get("/{pilot_id}/gate")
def pilot_gate(
    pilot_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    return evaluate_pilot_gate(
        db, tenant_id=current_user.tenant_id, pilot_id=pilot_id
    )


@router.get("/{pilot_id}/evidence")
def pilot_evidence(
    pilot_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    pilot = _pilot(db, current_user.tenant_id, pilot_id)
    metrics = db.query(InputPilotDailyMetric).filter(
        InputPilotDailyMetric.tenant_id == current_user.tenant_id,
        InputPilotDailyMetric.pilot_id == pilot.id,
    ).order_by(
        InputPilotDailyMetric.metric_date.desc(),
        InputPilotDailyMetric.journey_key.asc(),
    ).all()
    incidents = db.query(InputPilotIncident).filter(
        InputPilotIncident.tenant_id == current_user.tenant_id,
        InputPilotIncident.pilot_id == pilot.id,
    ).order_by(InputPilotIncident.occurred_at.desc()).all()
    audits = db.query(InputPilotAudit).filter(
        InputPilotAudit.tenant_id == current_user.tenant_id,
        InputPilotAudit.pilot_id == pilot.id,
    ).order_by(InputPilotAudit.audited_at.desc()).all()
    acceptance = db.query(InputPilotAcceptance).filter(
        InputPilotAcceptance.tenant_id == current_user.tenant_id,
        InputPilotAcceptance.pilot_id == pilot.id,
    ).first()
    return {
        "metric_rows": len(metrics),
        "latest_metrics": [
            {
                "id": str(row.id),
                "metric_date": row.metric_date,
                "journey_key": row.journey_key,
                "total_attempts": row.total_attempts,
                "successful_attempts": row.successful_attempts,
                "retry_count": row.retry_count,
                "manual_correction_count": row.manual_correction_count,
                "processing_p95_ms": row.processing_p95_ms,
                "retrieval_checks": row.retrieval_checks,
                "cited_retrievals": row.cited_retrievals,
                "friction_count": row.friction_count,
                "source_evidence_sha256": row.source_evidence_sha256,
            }
            for row in metrics[:20]
        ],
        "incidents": [
            {
                "id": str(row.id),
                "severity": row.severity,
                "category": row.category,
                "near_miss": row.near_miss,
                "status": row.status,
                "data_loss": row.data_loss,
                "unauthorized_access": row.unauthorized_access,
                "false_completion": row.false_completion,
                "summary": row.summary,
                "occurred_at": row.occurred_at,
                "resolved_at": row.resolved_at,
            }
            for row in incidents
        ],
        "audits": [
            {
                "id": str(row.id),
                "audit_type": row.audit_type,
                "status": row.status,
                "sample_size": row.sample_size,
                "findings": row.findings or [],
                "evidence_sha256": row.evidence_sha256,
                "audited_at": row.audited_at,
            }
            for row in audits
        ],
        "retrospective": (
            {
                "ref": pilot.retrospective_ref,
                "sha256": pilot.retrospective_sha256,
            }
            if pilot.retrospective_sha256
            else None
        ),
        "acceptance": (
            {
                "decision": acceptance.decision,
                "signer_name": acceptance.signer_name,
                "signer_role": acceptance.signer_role,
                "signed_document_ref": acceptance.signed_document_ref,
                "signed_document_sha256": acceptance.signed_document_sha256,
                "signed_at": acceptance.signed_at,
            }
            if acceptance is not None
            else None
        ),
    }


@router.post("/{pilot_id}/acceptance")
def record_acceptance(
    pilot_id: UUID,
    payload: AcceptanceIn,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    pilot = _pilot(db, current_user.tenant_id, pilot_id, lock=True)
    _require_running_pilot(pilot)
    signed_at = _as_utc(payload.signed_at)
    if signed_at < _as_utc(pilot.started_at) or signed_at > datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="signed_at 必須介於 Pilot 開始時間與現在")
    if payload.decision == "accepted":
        preflight = evaluate_pilot_gate(
            db,
            tenant_id=current_user.tenant_id,
            pilot_id=pilot.id,
            require_acceptance=False,
        )
        if preflight["status"] != "PASS":
            raise HTTPException(status_code=409, detail=preflight)
    row = InputPilotAcceptance(
        tenant_id=current_user.tenant_id,
        pilot_id=pilot.id,
        **{
            **payload.model_dump(),
            "signed_document_sha256": _require_sha256(
                payload.signed_document_sha256
            ),
        },
    )
    db.add(row)
    pilot.status = "accepted" if payload.decision == "accepted" else "rejected"
    pilot.completed_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Pilot acceptance 已存在且不可覆寫") from exc
    return evaluate_pilot_gate(
        db, tenant_id=current_user.tenant_id, pilot_id=pilot.id
    )
