import os
import uuid
import logging
import aiofiles
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import check_document_permission, can_access_document_by_department
from app.crud import crud_document
from app.models.user import User
from app.models.document import Document as DocumentModel
from app.schemas.document import Document, DocumentCreate
from app.config import settings
from app.crud import crud_tenant  # top-level import
from app.tasks.document_tasks import process_document_task
from app.services.document_parser import SUPPORTED_FORMATS

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
    if department_id:
        if not can_access_document_by_department(current_user, department_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限存取此部門的文件",
            )
        documents = (
            db.query(DocumentModel)
            .filter(
                DocumentModel.tenant_id == current_user.tenant_id,
                DocumentModel.department_id == department_id,
            )
            .order_by(DocumentModel.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    else:
        if current_user.is_superuser or current_user.role in ["owner", "admin", "hr"]:
            documents = crud_document.get_by_tenant(
                db, tenant_id=current_user.tenant_id, skip=skip, limit=limit
            )
        else:
            q = db.query(DocumentModel).filter(DocumentModel.tenant_id == current_user.tenant_id)
            if current_user.department_id is None:
                q = q.filter(DocumentModel.department_id.is_(None))
            else:
                q = q.filter(
                    or_(
                        DocumentModel.department_id.is_(None),
                        DocumentModel.department_id == current_user.department_id,
                    )
                )
            documents = (
                q.order_by(DocumentModel.created_at.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )
    return documents


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

    file_path = os.path.join(upload_dir, f"{document.id}{file_ext}")
    os.replace(temp_file_path, file_path)
    
    # 6. 觸發背景任務處理
    process_document_task.delay(
        document_id=str(document.id),
        file_path=file_path,
        tenant_id=str(current_user.tenant_id)
    )
    
    return document


@router.delete("/batch", summary="批次刪除所有文件")
def batch_delete_documents(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    批次刪除當前租戶的所有文件（含 chunks、實體檔案）。
    權限：owner, admin
    """
    if current_user.role not in ("owner", "admin") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="僅管理員可執行批次刪除")

    docs = (
        db.query(DocumentModel)
        .filter(DocumentModel.tenant_id == current_user.tenant_id)
        .all()
    )
    deleted = 0
    for doc in docs:
        for chunk in doc.chunks:
            db.delete(chunk)
        try:
            ext = os.path.splitext(doc.filename)[1]
            fp = os.path.join(settings.UPLOAD_DIR, str(doc.tenant_id), f"{doc.id}{ext}")
            if os.path.exists(fp):
                os.remove(fp)
        except Exception:
            pass
        db.delete(doc)
        deleted += 1
    db.commit()
    return {"deleted": deleted}


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
    document = crud_document.get(db, document_id=document_id)
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在"
        )
    
    # 權限檢查
    if not current_user.is_superuser and document.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="無權限訪問此文件"
        )
    
    return document


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
    
    if not document:
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
    
    # 刪除向量（pgvector: chunks 含有 embedding，直接刪除 DB 記錄即可）
    try:
        chunks = crud_document.get_chunks(db, document_id=document_id)
        for chunk in chunks:
            db.delete(chunk)
        db.commit()
    except Exception as e:
        logger.warning("刪除向量 chunks 失敗 (document_id=%s): %s", document_id, e)
    
    # 刪除實體文件
    try:
        file_ext = os.path.splitext(document.filename)[1]
        file_path = os.path.join(
            settings.UPLOAD_DIR,
            str(document.tenant_id),
            f"{document.id}{file_ext}"
        )
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logger.warning("刪除實體文件失敗 (document_id=%s): %s", document_id, e)
    
    # 刪除資料庫記錄
    crud_document.delete(db, document_id=document_id)
    
    return {"message": "文件已刪除", "document_id": str(document_id)}


