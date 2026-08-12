"""Task API — 版本化任務定義與 TaskRun（職能任務平台重構 Phase 2）。"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.task_engine import (
    TaskAccessDenied,
    TaskEngine,
    TaskEngineError,
    TaskHandlerNotImplemented,
    get_task_engine,
)

router = APIRouter()


class TaskRunCreate(BaseModel):
    idempotency_key: str = Field(..., min_length=8, max_length=128)
    inputs: Dict[str, Any] = Field(default_factory=dict)
    scene_context: Optional[Dict[str, Any]] = None


class TaskRunTransition(BaseModel):
    to_status: str


class TaskRunInputsPatch(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)
    sources: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    edited_fields: List[str] = Field(default_factory=list)


class TaskRunParseText(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    source: Literal["text", "voice"] = "text"
    source_ref: Optional[str] = Field(default=None, max_length=200)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


def _definition_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "task_key": row.task_key,
        "name": row.name,
        "description": row.description,
        "version": row.version,
        "status": row.status,
        "handler_key": row.handler_key,
        "module_key": row.module_key,
        "applicable_job_role_keys": row.applicable_job_role_keys or [],
        "input_schema": row.input_schema or {},
        "required_capabilities": row.required_capabilities or [],
        "output_bindings": row.output_bindings or [],
        "risk_level": row.risk_level,
    }


def _run_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "task_key": row.task_key,
        "task_version": row.task_version,
        "status": row.status,
        "module_key": row.module_key,
        "job_role_id": str(row.job_role_id) if row.job_role_id else None,
        "input_snapshot": row.input_snapshot or {},
        "field_sources": row.field_sources or {},
        "provenance": row.provenance or {},
        "error": row.error,
        "output_refs": row.output_refs or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _raise_engine(exc: Exception) -> None:
    if isinstance(exc, TaskAccessDenied):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, TaskHandlerNotImplemented):
        raise HTTPException(status_code=501, detail=str(exc))
    if isinstance(exc, TaskEngineError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=500, detail=str(exc))


@router.get("/tasks")
def list_tasks(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> List[Dict[str, Any]]:
    """列出目前租戶可用的任務定義（全域 + 租戶覆寫的最新 enabled 版本）。"""
    engine = get_task_engine(db)
    return [
        _definition_dict(row)
        for row in engine.list_accessible_definitions(current_user)
    ]


@router.post("/tasks/{task_key}/runs", status_code=201)
def start_task_run(
    task_key: str,
    body: TaskRunCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    """建立 TaskRun（idempotent：同 idempotency_key 回傳既有 run）。"""
    engine = get_task_engine(db)
    try:
        run, created = engine.start_run(
            user=current_user,
            task_key=task_key,
            inputs=body.inputs,
            idempotency_key=body.idempotency_key,
            scene=body.scene_context,
        )
        db.commit()
        payload = _run_dict(run)
        payload["created"] = created
        return payload
    except Exception as exc:
        db.rollback()
        _raise_engine(exc)


@router.get("/tasks/runs")
def list_task_runs(
    task_key: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> List[Dict[str, Any]]:
    """我的 TaskRun 清單（工作台 resume 用）。"""
    from app.models.mka import TaskRun

    q = db.query(TaskRun).filter(
        TaskRun.tenant_id == current_user.tenant_id,
        TaskRun.user_id == current_user.id,
    )
    if task_key:
        q = q.filter(TaskRun.task_key == task_key)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            q = q.filter(TaskRun.status.in_(statuses))
    rows = q.order_by(TaskRun.created_at.desc()).limit(20).all()
    return [_run_dict(r) for r in rows]


@router.get("/tasks/runs/{run_id}")
def get_task_run(
    run_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    run = _get_own_run(db, current_user, run_id)
    return _run_dict(run)


@router.patch("/tasks/runs/{run_id}/inputs")
def patch_task_run_inputs(
    run_id: UUID,
    body: TaskRunInputsPatch,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    """更新 run 的欄位值與來源；edited_fields 會記入 provenance.manual_edits。"""
    run = _get_own_run(db, current_user, run_id)
    if run.status not in {"draft", "in_progress"}:
        raise HTTPException(
            status_code=409, detail=f"狀態 {run.status} 不可編輯欄位"
        )
    engine = get_task_engine(db)
    snapshot = dict(run.input_snapshot or {})
    values = dict(snapshot.get("values") or {})
    values.update(body.values)
    snapshot["values"] = values
    run.input_snapshot = snapshot
    if body.sources:
        engine.record_field_sources(run, body.sources)
    for field_name in body.edited_fields:
        engine.record_manual_edit(run, field_name)
    db.commit()
    return _run_dict(run)


@router.post("/tasks/runs/{run_id}/parse-text")
def parse_task_run_text(
    run_id: UUID,
    body: TaskRunParseText,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    """轉寫／文字輸入 → 依任務表單抽取欄位（此端點不執行 STT）。

    抽取結果自動併入 run inputs，並保留 text／voice 來源資訊。
    """
    run = _get_own_run(db, current_user, run_id)
    if run.status not in {"draft", "in_progress"}:
        raise HTTPException(
            status_code=409, detail=f"狀態 {run.status} 不可編輯欄位"
        )

    # 以任務綁定表單的實際欄位作為抽取目標。
    from app.models.mka import TaskDefinition

    definition = (
        db.query(TaskDefinition)
        .filter(TaskDefinition.id == run.task_definition_id)
        .first()
    )
    schema = None
    for binding in (definition.output_bindings or []) if definition else []:
        if binding.get("kind") == "form" and binding.get("form_key"):
            from app.services.fixed_form import get_form_registry

            schema = get_form_registry().get(binding["form_key"])
            if schema is not None:
                break

    from app.services.voice_gateway import get_voice_gateway

    gateway = get_voice_gateway()
    if schema is not None:
        details = gateway.extract_form_fields(body.text, schema.fields)
    else:
        details = gateway.extract_confirm_fields(
            body.text,
            ["amount", "unit_price", "part_number", "quantity", "date", "customer"],
        )

    # 併入 run inputs；key 用表單欄位名而非通用抽取型別。
    # 數字／金額欄位轉成 number，避免後續 validate／execute 因 str 型別失敗。
    _NUMERIC_FIELDS = {"quantity", "unit_price", "amount", "tax_rate"}
    engine = get_task_engine(db)
    snapshot = dict(run.input_snapshot or {})
    values = dict(snapshot.get("values") or {})
    sources: Dict[str, Dict[str, Any]] = {}
    detected_values: Dict[str, Any] = {}
    for item in details:
        field_name = item.get("type")
        value = item.get("value")
        if not field_name or value in (None, ""):
            continue
        if field_name in _NUMERIC_FIELDS or item.get("type") in _NUMERIC_FIELDS:
            try:
                raw = str(value).replace(",", "").strip()
                value = float(raw) if "." in raw else int(raw)
            except (TypeError, ValueError):
                pass
        values[field_name] = value
        detected_values[field_name] = value
        sources[field_name] = {
            "source": body.source,
            "ref": body.source_ref,
            "confidence": body.confidence,
        }
    snapshot["values"] = values
    run.input_snapshot = snapshot
    if sources:
        engine.record_field_sources(run, sources)
    db.commit()

    return {"run": _run_dict(run), "detected_fields": detected_values}


@router.post("/tasks/runs/{run_id}/execute")
def execute_task_run(
    run_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    run = _get_own_run(db, current_user, run_id)
    engine = get_task_engine(db)
    try:
        engine.execute(run, current_user)
        db.commit()
        return _run_dict(run)
    except Exception as exc:
        db.rollback()
        _raise_engine(exc)


@router.post("/tasks/runs/{run_id}/transition")
def transition_task_run(
    run_id: UUID,
    body: TaskRunTransition,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    run = _get_own_run(db, current_user, run_id)
    # 擁有者只能操作自己的生命週期；審核結果（approved/rejected）與執行
    # （executed/exported）必須走簽核流程或管理員，禁止自批／自執行。
    owner_allowed = {
        ("draft", "in_progress"),
        ("rejected", "draft"),
        ("failed", "draft"),
    }
    is_admin = bool(current_user.is_superuser) or current_user.role in {"owner", "admin"}
    if (run.status, body.to_status) not in owner_allowed and not is_admin:
        raise HTTPException(
            status_code=403,
            detail="此狀態轉換需經簽核流程或管理員權限",
        )
    engine = get_task_engine(db)
    try:
        engine.transition(run, body.to_status)
        db.commit()
        return _run_dict(run)
    except Exception as exc:
        db.rollback()
        _raise_engine(exc)


# ── 租戶管理員：任務定義覆寫（設定中心）──

class TaskDefinitionOverride(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: str = "enabled"
    applicable_job_role_keys: Optional[List[str]] = None
    required_capabilities: Optional[List[str]] = None
    input_schema: Optional[Dict[str, Any]] = None
    risk_level: Optional[str] = None


class TaskDefinitionStatusUpdate(BaseModel):
    status: str  # enabled | disabled | deprecated


def _require_admin(user: User) -> None:
    if not (user.is_superuser or user.role in {"owner", "admin"}):
        raise HTTPException(status_code=403, detail="admin required")


@router.get("/tasks/definitions")
def list_task_definitions_admin(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> List[Dict[str, Any]]:
    """全部定義（全域 + 本租戶覆寫，含版本）— 設定中心用。"""
    _require_admin(current_user)
    from app.models.mka import TaskDefinition

    rows = (
        db.query(TaskDefinition)
        .filter(
            (TaskDefinition.tenant_id == current_user.tenant_id)
            | (TaskDefinition.tenant_id.is_(None))
        )
        .order_by(TaskDefinition.task_key, TaskDefinition.version)
        .all()
    )
    return [
        {**_definition_dict(r), "scope": "tenant" if r.tenant_id else "global"}
        for r in rows
    ]


@router.post("/tasks/definitions/{task_key}/override", status_code=201)
def override_task_definition(
    task_key: str,
    body: TaskDefinitionOverride,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    """建立租戶覆寫版本（不改全域定義；版本號自動遞增）。"""
    _require_admin(current_user)
    from app.models.mka import TaskDefinition

    base = get_task_engine(db).resolve_definition(current_user.tenant_id, task_key)
    if base is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_key}")

    existing_versions = (
        db.query(TaskDefinition)
        .filter(
            TaskDefinition.tenant_id == current_user.tenant_id,
            TaskDefinition.task_key == task_key,
        )
        .all()
    )
    next_minor = len(existing_versions) + 1
    version = f"1.{next_minor}"

    row = TaskDefinition(
        tenant_id=current_user.tenant_id,
        task_key=task_key,
        name=body.name or base.name,
        description=body.description if body.description is not None else base.description,
        version=version,
        status=body.status,
        handler_key=base.handler_key,
        module_key=base.module_key,
        applicable_job_role_keys=(
            body.applicable_job_role_keys
            if body.applicable_job_role_keys is not None
            else list(base.applicable_job_role_keys or [])
        ),
        required_capabilities=(
            body.required_capabilities
            if body.required_capabilities is not None
            else list(base.required_capabilities or [])
        ),
        input_schema=(
            body.input_schema
            if body.input_schema is not None
            else dict(base.input_schema or {})
        ),
        approval_policy_id=base.approval_policy_id,
        output_bindings=list(base.output_bindings or []),
        risk_level=body.risk_level or base.risk_level,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {**_definition_dict(row), "scope": "tenant"}


@router.patch("/tasks/definitions/{definition_id}")
def update_task_definition_status(
    definition_id: UUID,
    body: TaskDefinitionStatusUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    """調整租戶覆寫定義的狀態（全域定義不可改）。"""
    _require_admin(current_user)
    from app.models.mka import TaskDefinition

    if body.status not in {"enabled", "disabled", "deprecated"}:
        raise HTTPException(status_code=422, detail="invalid status")
    row = (
        db.query(TaskDefinition)
        .filter(
            TaskDefinition.id == definition_id,
            TaskDefinition.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="tenant override not found")
    row.status = body.status
    db.commit()
    return {**_definition_dict(row), "scope": "tenant"}


@router.get("/tasks/metrics/summary")
def task_metrics_summary(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    """租戶任務指標彙總（完成率／修改率／錯誤率／欄位來源／簽核效率）。"""
    _require_admin(current_user)
    from app.services.task_metrics import compute_task_metrics

    return compute_task_metrics(db, current_user.tenant_id)


@router.get("/tasks/runs/{run_id}/events")
def list_run_events(
    run_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> List[Dict[str, Any]]:
    """單一 run 的事件流（本人或管理員）。"""
    from app.models.mka import TaskRunEvent

    run = _get_own_run(db, current_user, run_id)
    rows = (
        db.query(TaskRunEvent)
        .filter(TaskRunEvent.run_id == run.id)
        .order_by(TaskRunEvent.created_at)
        .all()
    )
    return [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "actor_id": str(e.actor_id) if e.actor_id else None,
            "payload": e.payload or {},
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]


def _get_own_run(db: Session, user: User, run_id: UUID):
    from app.models.mka import TaskRun

    run = (
        db.query(TaskRun)
        .filter(TaskRun.id == run_id, TaskRun.tenant_id == user.tenant_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="task run not found")
    is_reviewer = bool(user.is_superuser or user.role in {"owner", "admin"})
    if run.user_id != user.id and not is_reviewer:
        raise HTTPException(status_code=403, detail="not your task run")
    return run
