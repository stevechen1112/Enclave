import logging
import os
import uuid
from typing import Any, Dict, List, Optional
from uuid import UUID

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import (
    can_access_document_by_department,
    check_document_permission,
)
from app.config import settings
from app.core.authorization import AuthorizationContext
from app.crud import crud_document, crud_tenant
from app.models.document import Document as DocumentModel
from app.models.user import User
from app.schemas.document import Document, DocumentCreate
from app.services.document_readiness import (
    apply_answer_ready_filter,
    load_document_answer_states,
    serialize_document,
)
from app.services.document_parser import SUPPORTED_FORMATS
from app.services.document_visibility import apply_document_visibility
from app.services.kb_scope_policy import resolve_kb_revision_scope
from app.tasks.document_tasks import process_document_task

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Response schema for /supported-formats ──────────────────────────────────────
class SupportedFormatsResponse(BaseModel):
    extensions: List[str]
    type_map: Dict[str, str]


@router.get("/supported-formats", response_model=SupportedFormatsResponse)
def get_supported_formats() -> SupportedFormatsResponse:
    """
    公開端點：回傳後端支援的上傳格式清單，供前端動態使用。
    不需要認證，讓登入畫面前也能快取格式清單。
    """
    return SupportedFormatsResponse(
        extensions=sorted(SUPPORTED_FORMATS.keys()),
        type_map=SUPPORTED_FORMATS,
    )


@router.get("/", response_model=List[Document])
def list_documents(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    department_id: Optional[UUID] = Query(None, description="Filter by department"),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    獲取當前租戶的文件列表，可依部門篩選
    """
    authz = AuthorizationContext.from_user(current_user)
    if department_id and not can_access_document_by_department(current_user, department_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="無權限存取此部門的文件",
        )
    query = apply_document_visibility(
        db.query(DocumentModel), authz=authz, db=db, require_completed=False
    )
    if department_id:
        query = query.filter(DocumentModel.department_id == department_id)
    can_manage = current_user.is_superuser or current_user.role in {"owner", "admin", "hr"}
    allowed_revision_ids = None
    if not can_manage:
        scope = resolve_kb_revision_scope(authz=authz, requested=None, db=db)
        allowed_revision_ids = [UUID(value) for value in scope["kb_revision_ids"]]
        query = apply_answer_ready_filter(
            query,
            tenant_id=current_user.tenant_id,
            db=db,
            kb_revision_ids=allowed_revision_ids,
        )
    documents = (
        query.order_by(DocumentModel.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    states = load_document_answer_states(
        db,
        tenant_id=current_user.tenant_id,
        documents=documents,
        kb_revision_ids=allowed_revision_ids,
    )
    return [serialize_document(document, states[document.id]) for document in documents]


@router.post("/upload", response_model=Document)
async def upload_document(
    *,
    db: Session = Depends(deps.get_db),
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    上傳文件
    - 支援 PDF(文字/掃描/表格)、DOCX、DOC、TXT、Excel、CSV、HTML、Markdown、RTF、JSON、圖片
    - 非同步處理：解析、切片、向量化
    - 權限：owner, admin, hr
    """
    # 權限檢查
    check_document_permission(current_user, "create")

    # 文件數量配額檢查
    doc_quota = crud_tenant.check_quota(db, current_user.tenant_id, "document")
    if not doc_quota.get("allowed", True):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "quota_exceeded",
                "message": doc_quota.get("message", "文件數量配額已超過"),
                "current": doc_quota.get("current"),
                "limit": doc_quota.get("limit"),
            },
        )

    # 1. 驗證文件類型（支援所有 Phase 0-2 格式）
    from app.services.document_parser import DocumentParser, SUPPORTED_FORMATS
    allowed_extensions = set(SUPPORTED_FORMATS.keys())
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支援的文件類型: {file_ext}。支援的類型: {', '.join(sorted(allowed_extensions))}"
        )
    
    # 2. 偵測文件類型
    try:
        file_type = DocumentParser.detect_file_type(file.filename)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    # 3. 清理檔名（去除資料夾路徑前綴，如 webkitRelativePath）
    clean_filename = os.path.basename(file.filename or "")
    if not clean_filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="無效的檔名")

    # 4. 串流寫檔（避免一次把整個檔案讀進記憶體）
    upload_dir = os.path.join(settings.UPLOAD_DIR, str(current_user.tenant_id))
    os.makedirs(upload_dir, exist_ok=True)
    temp_file_path = os.path.join(upload_dir, f"tmp-{uuid.uuid4().hex}{file_ext}")

    file_size = 0
    chunk_size = 1024 * 1024  # 1MB
    try:
        async with aiofiles.open(temp_file_path, "wb") as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > settings.MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"文件過大（{file_size / 1024 / 1024:.2f} MB），"
                            f"上限為 {settings.MAX_FILE_SIZE / 1024 / 1024} MB"
                        ),
                    )
                await f.write(chunk)
    except HTTPException:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise
    except Exception:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise
    finally:
        await file.close()

    if file_size == 0:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件為空"
        )

    # CG-CLAMAV：上傳掃毒（fail-closed 於 SaaS／託管；地端 CLAMAV_ENABLED=false 跳過）
    import asyncio
    from app.services.file_scan import MalwareDetectedError, FileScanError, scan_file_path

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, lambda: scan_file_path(temp_file_path, clean_filename)
        )
    except MalwareDetectedError as exc:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"檔案未通過安全掃描: {exc.signature}",
        )
    except FileScanError:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        if settings.CLAMAV_FAIL_CLOSED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="檔案安全掃描服務暫時不可用，請稍後再試",
            )

    # 儲存配額檢查（FOR UPDATE + 同 transaction create，防 TOCTOU）
    storage_quota = crud_tenant.lock_and_check_storage_quota(
        db, current_user.tenant_id, file_size
    )
    if not storage_quota.get("allowed", True):
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        try:
            from app.observability.business_metrics import record_quota_exceeded

            record_quota_exceeded("storage")
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "quota_exceeded",
                "axis": "storage",
                "message": storage_quota.get("message", "儲存空間配額已超過"),
                "current": storage_quota.get("current"),
                "limit": storage_quota.get("limit"),
            },
        )

    # 5. 建立文件記錄
    doc_in = DocumentCreate(
        filename=clean_filename,
        file_type=file_type
    )
    
    try:
        document = crud_document.create(
            db,
            obj_in=doc_in,
            tenant_id=current_user.tenant_id,
            uploaded_by=current_user.id,
            file_size=file_size
        )
    except Exception:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise

    # 5.5 經 StorageBackend 上架（ADR-011）：local=搬入 UPLOAD_DIR；s3=上傳物件儲存
    from app.services.storage import build_storage_key, get_storage_backend

    backend = get_storage_backend()
    storage_key = build_storage_key(current_user.tenant_id, document.id, file_ext)
    try:
        content_uri = backend.put(storage_key, temp_file_path)
    except Exception:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        # 文件列已在 create 時 commit；put 失敗必須 tombstone，
        # 否則留下無內容的孤兒記錄（S3 後端是網路操作，失敗率非零）
        try:
            crud_document.tombstone(db, document_id=document.id, reason="storage_put_failed")
        except Exception:
            logger.error("tombstone after storage put failure also failed: doc=%s", document.id)
        raise

    # content_uri 持久化（local=絕對路徑，向後相容；s3=s3://bucket/key）
    document.file_path = content_uri
    db.commit()

    # 6. 觸發背景任務處理
    process_document_task.delay(
        document_id=str(document.id),
        file_path=content_uri,
        tenant_id=str(current_user.tenant_id)
    )

    return document


@router.delete("/batch", summary="批次撤銷所有文件（tombstone + outbox）")
def batch_delete_documents(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    批次撤銷當前租戶文件：走與單筆刪除相同的 DocumentRevocationService。
    權限：owner, admin
    """
    if current_user.role not in ("owner", "admin") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="僅管理員可執行批次刪除")

    from app.services.document_revocation import get_document_revocation

    docs = (
        db.query(DocumentModel)
        .filter(
            DocumentModel.tenant_id == current_user.tenant_id,
            DocumentModel.tombstoned_at.is_(None),
        )
        .all()
    )
    revoked = 0
    failed = []
    revocation = get_document_revocation()
    for doc in docs:
        result = revocation.revoke(
            db,
            document_id=doc.id,
            actor_id=current_user.id,
            tenant_id=current_user.tenant_id,
            reason="batch_delete",
        )
        if result.get("ok"):
            revoked += 1
        else:
            failed.append(result)
    return {"deleted": revoked, "revoked": revoked, "failed": failed, "deny_first": True}


@router.get("/{document_id}", response_model=Document)
def get_document(
    *,
    db: Session = Depends(deps.get_db),
    document_id: UUID,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    獲取文件詳情
    """
    authz = AuthorizationContext.from_user(current_user)
    query = apply_document_visibility(
        db.query(DocumentModel).filter(DocumentModel.id == document_id),
        authz=authz,
        db=db,
        require_completed=False,
    )
    can_manage = current_user.is_superuser or current_user.role in {"owner", "admin", "hr"}
    allowed_revision_ids = None
    if not can_manage:
        scope = resolve_kb_revision_scope(authz=authz, requested=None, db=db)
        allowed_revision_ids = [UUID(value) for value in scope["kb_revision_ids"]]
        query = apply_answer_ready_filter(
            query,
            tenant_id=current_user.tenant_id,
            db=db,
            kb_revision_ids=allowed_revision_ids,
        )
    document = query.first()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    state = load_document_answer_states(
        db,
        tenant_id=current_user.tenant_id,
        documents=[document],
        kb_revision_ids=allowed_revision_ids,
    )[document.id]
    return serialize_document(document, state)


@router.delete("/{document_id}")
def delete_document(
    *,
    db: Session = Depends(deps.get_db),
    document_id: UUID,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    刪除文件
    - 刪除資料庫記錄
    - 刪除實體文件
    - 刪除 pgvector 向量（透過 DB cascade 或手動刪除 chunks）
    - 權限：owner, admin, hr
    """
    # 權限檢查
    check_document_permission(current_user, "delete")
    
    document = crud_document.get(db, document_id=document_id)
    
    if not document or document.tombstoned_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在"
        )
    
    # 權限檢查
    if not current_user.is_superuser and document.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="無權限刪除此文件"
        )

    if not can_access_document_by_department(current_user, document.department_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="無權限刪除此部門的文件",
        )

    from app.services.document_revocation import get_document_revocation
    result = get_document_revocation().revoke(
        db,
        document_id=document_id,
        actor_id=current_user.id,
        tenant_id=current_user.tenant_id,
        reason="user_request",
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在或已刪除",
        )
    return {"message": "文件已刪除", "document_id": str(document_id), "deny_first": True}
