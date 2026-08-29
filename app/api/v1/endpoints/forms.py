"""Fixed Form API, including tenant-scoped persistent form instances."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.workflow_repository import (
    WorkflowConflictError,
    WorkflowForbiddenError,
    WorkflowNotFoundError,
    WorkflowRepository,
    form_definition_to_dict,
    form_instance_to_dict,
    approval_to_dict,
)

router = APIRouter()


class ValidateRequest(BaseModel):
    values: Dict[str, Any]


class FormCreateRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    module_key: Optional[str] = None
    scene_context: Dict[str, Any] = Field(default_factory=dict)


class FormPatchRequest(BaseModel):
    record_version: int
    values: Dict[str, Any]
    provenance: Dict[str, Any] = Field(default_factory=dict)


class VersionRequest(BaseModel):
    record_version: int


class FormSubmitRequest(VersionRequest):
    idempotency_key: str


class FormExportRequest(BaseModel):
    format: str = "pdf"  # pdf | docx | xlsx | md
    async_export: bool = False  # True 時排入 Celery 佇列，完成後經 exports 下載


_EXPORT_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown; charset=utf-8",
}


def _raise_workflow(exc: Exception) -> None:
    if isinstance(exc, WorkflowNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, WorkflowForbiddenError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, WorkflowConflictError):
        raise HTTPException(status_code=409, detail=str(exc))
    raise HTTPException(status_code=400, detail=str(exc))


def _actor_kwargs(user: User) -> Dict[str, Any]:
    """Endpoint-layer actor context; repository performs authoritative check."""
    return {
        "actor_id": user.id,
        "actor_roles": [user.role],
        "is_superuser": bool(user.is_superuser),
    }


@router.get("/forms")
async def list_forms(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """列出目前租戶的 active 表單；第一次讀取時 lazy seed。"""
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")
    rows = WorkflowRepository(db).list_form_definitions(tenant_id=current_user.tenant_id)
    from app.services.job_context import available_form_keys

    allowed = available_form_keys(db, current_user)
    rows = [row for row in rows if row.form_key in allowed]
    db.commit()
    return {
        "forms": [row.form_key for row in rows],
        "definitions": [form_definition_to_dict(row) for row in rows],
    }


@router.get("/forms/{form_name}/schema")
async def get_form_schema(
    form_name: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """取得租戶擁有的表單 schema。"""
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")
    # 直接 URL 授權：表單所屬模組必須對目前職能上下文可用（不只隱藏選單）
    from app.services.job_context import ModuleAccessDenied, assert_form_access

    try:
        assert_form_access(db, current_user, form_name)
    except ModuleAccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    try:
        row = WorkflowRepository(db).get_form_definition(
            tenant_id=current_user.tenant_id, form_key=form_name
        )
        db.commit()
        payload = form_definition_to_dict(row)
        payload.update(row.json_schema or {})
        return payload
    except Exception as exc:
        db.rollback()
        _raise_workflow(exc)


@router.post("/forms/{form_name}/validate")
async def validate_form(
    form_name: str,
    request: ValidateRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """驗證表單值。"""
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")
    # 與 schema／instances 一致的直接 URL 授權
    from app.services.job_context import ModuleAccessDenied, assert_form_access

    try:
        assert_form_access(db, current_user, form_name)
    except ModuleAccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    # 與建單／validate_form 同一條 schema 來源：租戶 DB 的 FormDefinition
    try:
        result = WorkflowRepository(db).validate_form_values(
            tenant_id=current_user.tenant_id,
            form_key=form_name,
            values=request.values,
        )
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        _raise_workflow(exc)


@router.post("/forms/{form_name}/instances")
def create_form_instance(
    form_name: str,
    request: FormCreateRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")
    # 直接 URL 授權：建立表單視同執行該模組任務
    from app.services.job_context import ModuleAccessDenied, assert_form_access

    try:
        assert_form_access(db, current_user, form_name)
    except ModuleAccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    try:
        row = WorkflowRepository(db).create_form_instance(
            tenant_id=current_user.tenant_id,
            owner_id=current_user.id,
            form_key=form_name,
            values=request.values,
            provenance=request.provenance,
            module_key=request.module_key,
            scene_context=request.scene_context,
        )
        db.commit()
        db.refresh(row)
        return form_instance_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_workflow(exc)


@router.get("/forms/instances")
def list_my_form_instances(
    status: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """我的草稿／待審／已核准 instance 清單。"""
    from app.models.workflow import FormInstance

    q = db.query(FormInstance).filter(FormInstance.tenant_id == current_user.tenant_id)
    is_reviewer = bool(
        current_user.is_superuser or current_user.role in {"owner", "admin"}
    )
    if not is_reviewer:
        q = q.filter(FormInstance.owner_id == current_user.id)
    if status:
        # 支援逗號分隔：draft,pending_review,approved
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            q = q.filter(FormInstance.status.in_(statuses))
    rows = q.order_by(FormInstance.updated_at.desc().nullslast(), FormInstance.created_at.desc()).limit(100).all()
    return [form_instance_to_dict(r) for r in rows]


@router.get("/forms/instances/{instance_id}")
def get_form_instance(
    instance_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row = WorkflowRepository(db).get_form_instance(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            **_actor_kwargs(current_user),
        )
        return form_instance_to_dict(row)
    except Exception as exc:
        _raise_workflow(exc)


@router.patch("/forms/instances/{instance_id}")
def patch_form_instance(
    instance_id: UUID,
    request: FormPatchRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row = WorkflowRepository(db).patch_form_instance(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            **_actor_kwargs(current_user),
            expected_version=request.record_version,
            values=request.values,
            provenance=request.provenance,
        )
        db.commit()
        db.refresh(row)
        return form_instance_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_workflow(exc)


@router.post("/forms/instances/{instance_id}/calculate")
def calculate_form_instance(
    instance_id: UUID,
    request: VersionRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row = WorkflowRepository(db).calculate_form(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            **_actor_kwargs(current_user),
            expected_version=request.record_version,
        )
        db.commit()
        db.refresh(row)
        return form_instance_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_workflow(exc)


@router.post("/forms/instances/{instance_id}/validate")
def validate_form_instance(
    instance_id: UUID,
    request: VersionRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row = WorkflowRepository(db).validate_form(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            **_actor_kwargs(current_user),
            expected_version=request.record_version,
        )
        db.commit()
        db.refresh(row)
        return form_instance_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_workflow(exc)


@router.post("/forms/instances/{instance_id}/submit")
def submit_form_instance(
    instance_id: UUID,
    request: FormSubmitRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row, approval = WorkflowRepository(db).submit_form(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            submitted_by=current_user.id,
            expected_version=request.record_version,
            idempotency_key=request.idempotency_key,
        )
        db.commit()
        db.refresh(row)
        db.refresh(approval)
        return {
            "form": form_instance_to_dict(row),
            "approval": approval_to_dict(approval),
        }
    except Exception as exc:
        db.rollback()
        _raise_workflow(exc)


@router.post("/forms/instances/{instance_id}/export")
def export_form_instance(
    instance_id: UUID,
    request: FormExportRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """匯出已核准表單（PDF/Word/Excel/Markdown）；未核准一律拒絕。

    async_export=true 時先做 approved 預檢再排入 Celery 佇列（202），
    完成後由 GET /forms/instances/{id}/exports 取得 storage_key 下載。
    """
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")

    fmt = (request.format or "").lower()
    if fmt not in WorkflowRepository._EXPORT_FORMATS:
        raise HTTPException(
            status_code=400, detail=f"unsupported export format: {request.format}"
        )

    if request.async_export:
        try:
            WorkflowRepository(db).assert_form_exportable(
                tenant_id=current_user.tenant_id,
                instance_id=instance_id,
                **_actor_kwargs(current_user),
            )
        except Exception as exc:
            _raise_workflow(exc)
        from app.tasks.mka_tasks import render_form_export
        task = render_form_export.delay(
            str(current_user.tenant_id),
            str(instance_id),
            str(current_user.id),
            fmt,
        )
        return JSONResponse(
            status_code=202,
            content={"status": "queued", "task_id": task.id, "format": fmt},
        )

    from app.observability.business_metrics import record_mka_form_export
    try:
        result = WorkflowRepository(db).export_form(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            **_actor_kwargs(current_user),
            format=request.format,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        _raise_workflow(exc)
    record_mka_form_export(format=result.format, success=result.success)
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "export render failed")
    from fastapi.responses import Response
    return Response(
        content=result.content,
        media_type=_EXPORT_MEDIA_TYPES[result.format],
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )


@router.get("/forms/instances/{instance_id}/exports")
def list_form_exports(
    instance_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """列出表單的匯出 artifact（含非同步匯出的 storage_key）。"""
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")
    try:
        row = WorkflowRepository(db).get_form_instance(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            **_actor_kwargs(current_user),
        )
        return {"exports": row.export_artifacts or []}
    except Exception as exc:
        _raise_workflow(exc)


@router.get("/forms/instances/{instance_id}/exports/{artifact_index}/download")
def download_form_export(
    instance_id: UUID,
    artifact_index: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """下載非同步匯出完成的檔案（StorageBackend 取回，租戶前綴強制檢查）。"""
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")
    try:
        row = WorkflowRepository(db).get_form_instance(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            **_actor_kwargs(current_user),
        )
    except Exception as exc:
        _raise_workflow(exc)
    artifacts = list(row.export_artifacts or [])
    if artifact_index < 0 or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="export artifact not found")
    artifact = artifacts[artifact_index]
    storage_key = artifact.get("storage_key")
    if not storage_key:
        raise HTTPException(
            status_code=409,
            detail="artifact has no stored file（同步匯出不落儲存；請用 async_export）",
        )
    from app.services.storage import assert_key_matches_tenant, get_storage_backend
    try:
        assert_key_matches_tenant(storage_key, str(current_user.tenant_id))
    except ValueError:
        raise HTTPException(status_code=403, detail="forbidden")
    content = get_storage_backend().get_bytes(storage_key)
    fmt = artifact.get("format", "md")
    from fastapi.responses import Response
    return Response(
        content=content,
        media_type=_EXPORT_MEDIA_TYPES.get(fmt, "application/octet-stream"),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{artifact.get("filename", f"export.{fmt}")}"'
            )
        },
    )
