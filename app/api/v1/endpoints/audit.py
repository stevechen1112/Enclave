from typing import Any, List, Optional
from uuid import UUID
from datetime import datetime
import csv
import io
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import check_audit_permission
from app.crud import crud_audit
from app.models.user import User
from app.schemas.audit import AuditLog, UsageSummary, UsageByActionType, UsageRecord

router = APIRouter()


@router.get("/logs", response_model=List[AuditLog])
def get_audit_logs(
    db: Session = Depends(deps.get_db),
    action: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    獲取稽核日誌
    - 權限：owner, admin
    - Superuser 可查看所有租戶
    - 一般用戶只能查看自己租戶的日誌
    """
    # 權限檢查
    check_audit_permission(current_user)
    
    logs = crud_audit.get_audit_logs(
        db,
        tenant_id=current_user.tenant_id,
        action=action,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit
    )
    return logs


@router.get("/usage/summary", response_model=UsageSummary)
def get_usage_summary(
    db: Session = Depends(deps.get_db),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    獲取用量摘要統計
    - 權限：owner, admin
    """
    # 權限檢查
    check_audit_permission(current_user)
    
    summary = crud_audit.get_usage_summary(
        db,
        tenant_id=current_user.tenant_id,
        start_date=start_date,
        end_date=end_date
    )
    return summary


@router.get("/usage/by-action", response_model=List[UsageByActionType])
def get_usage_by_action(
    db: Session = Depends(deps.get_db),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    按操作類型統計用量
    - 權限：owner, admin, hr
    """
    # 權限檢查
    check_audit_permission(current_user)
    
    usage = crud_audit.get_usage_by_action_type(
        db,
        tenant_id=current_user.tenant_id,
        start_date=start_date,
        end_date=end_date
    )
    return usage


# ─── 個人用量端點（所有登入用戶可查詢自己的數據）───

@router.get("/usage/me/summary", response_model=UsageSummary)
def get_my_usage_summary(
    db: Session = Depends(deps.get_db),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    取得目前登入用戶的個人用量摘要
    - 權限：所有登入用戶（只能查自己）
    """
    return crud_audit.get_usage_summary(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/usage/me/by-action", response_model=List[UsageByActionType])
def get_my_usage_by_action(
    db: Session = Depends(deps.get_db),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    取得目前登入用戶的個人用量（按類型分析）
    - 權限：所有登入用戶（只能查自己）
    """
    return crud_audit.get_usage_by_action_type(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/usage/records", response_model=List[UsageRecord])
def get_usage_records(
    db: Session = Depends(deps.get_db),
    action_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    獲取詳細用量記錄
    - 權限：owner, admin
    """
    # 權限檢查
    check_audit_permission(current_user)
    
    records = crud_audit.get_usage_records(
        db,
        tenant_id=current_user.tenant_id,
        action_type=action_type,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit
    )
    return records


# ─── Export Helpers ───

def _csv_stream(rows: list, columns: list[tuple[str, str]]) -> StreamingResponse:
    """產生 CSV StreamingResponse"""
    output = io.StringIO()
    # Add BOM for Excel UTF-8 compatibility
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow([label for _, label in columns])
    for row in rows:
        writer.writerow([_get_field(row, key) for key, _ in columns])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=report.csv"},
    )


def _get_field(obj: Any, key: str) -> Any:
    """從 ORM 物件或 dict 取值"""
    if isinstance(obj, dict):
        return obj.get(key, "")
    return getattr(obj, key, "")


def _pdf_stream(title: str, rows: list, columns: list[tuple[str, str]]) -> StreamingResponse:
    """產生 PDF StreamingResponse"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    story = []

    # Title
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 6*mm))

    # Table data
    header = [label for _, label in columns]
    data = [header]
    for row in rows:
        data.append([str(_get_field(row, key)) for key, _ in columns])

    if len(data) == 1:
        data.append(["No data"] + [""] * (len(header) - 1))

    col_widths = [max(60, 700 // len(columns))] * len(columns)
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={title}.pdf"},
    )


# ─── Export Endpoints ───

@router.get("/logs/export")
def export_audit_logs(
    format: str = Query("csv", regex="^(csv|pdf)$"),
    action: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 5000,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    匯出稽核日誌 (CSV / PDF)
    - 權限：owner, admin
    """
    check_audit_permission(current_user)

    logs = crud_audit.get_audit_logs(
        db,
        tenant_id=current_user.tenant_id,
        action=action,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit,
    )
    columns = [
        ("id", "ID"),
        ("created_at", "Time"),
        ("action", "Action"),
        ("actor_user_id", "User ID"),
        ("resource_type", "Resource Type"),
        ("resource_id", "Resource ID"),
        ("ip_address", "IP Address"),
    ]
    if format == "pdf":
        return _pdf_stream("Audit Logs Report", logs, columns)
    return _csv_stream(logs, columns)


@router.get("/usage/export")
def export_usage_records(
    format: str = Query("csv", regex="^(csv|pdf)$"),
    action_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 5000,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    匯出用量記錄 (CSV / PDF)
    - 權限：owner, admin
    """
    check_audit_permission(current_user)

    records = crud_audit.get_usage_records(
        db,
        tenant_id=current_user.tenant_id,
        action_type=action_type,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit,
    )
    columns = [
        ("id", "ID"),
        ("created_at", "Time"),
        ("action_type", "Action Type"),
        ("user_id", "User ID"),
        ("input_tokens", "Input Tokens"),
        ("output_tokens", "Output Tokens"),
        ("pinecone_queries", "Pinecone Queries"),
        ("embedding_calls", "Embedding Calls"),
        ("estimated_cost_usd", "Est. Cost (USD)"),
    ]
    if format == "pdf":
        return _pdf_stream("Usage Records Report", records, columns)
    return _csv_stream(records, columns)


# 輔助函數：記錄稽核日誌
def log_audit(
    db: Session,
    request: Request,
    current_user: User,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None
):
    """記錄稽核日誌"""
    ip_address = request.client.host if request.client else None
    
    crud_audit.create_audit_log(
        db,
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address
    )


# 輔助函數：記錄用量
def log_usage(
    db: Session,
    tenant_id: UUID,
    user_id: Optional[UUID],
    action_type: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    pinecone_queries: int = 0,
    embedding_calls: int = 0,
    metadata: Optional[dict] = None
):
    """記錄用量"""
    # 成本估算（範例費率，實際應從配置讀取）
    COST_PER_INPUT_TOKEN = 0.00001  # $0.01 per 1K tokens
    COST_PER_OUTPUT_TOKEN = 0.00003  # $0.03 per 1K tokens
    COST_PER_PINECONE_QUERY = 0.0001  # $0.0001 per query
    COST_PER_EMBEDDING_CALL = 0.0001  # $0.0001 per call
    
    estimated_cost = (
        input_tokens * COST_PER_INPUT_TOKEN +
        output_tokens * COST_PER_OUTPUT_TOKEN +
        pinecone_queries * COST_PER_PINECONE_QUERY +
        embedding_calls * COST_PER_EMBEDDING_CALL
    )
    
    crud_audit.create_usage_record(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action_type=action_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        pinecone_queries=pinecone_queries,
        embedding_calls=embedding_calls,
        estimated_cost=estimated_cost,
        metadata=metadata
    )
