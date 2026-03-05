"""
Phase 10 — Agent 管理 API

提供給前端使用的 REST API：
  GET  /agent/status          — Agent 目前狀態（運行中/停止/掃描中）
  GET  /agent/folders         — 已設定的監控資料夾清單
  POST /agent/folders         — 新增監控資料夾
  DELETE /agent/folders/{id}  — 移除監控資料夾
  POST /agent/scan            — 手動觸發立即掃描
  POST /agent/start           — 啟動 Agent 監控
  POST /agent/stop            — 停止 Agent 監控

  GET  /agent/review          — 取得待審核清單（支援分頁、信心度篩選）
  POST /agent/review/{id}/approve   — 核准單一項目
  POST /agent/review/{id}/reject    — 拒絕入庫
  POST /agent/review/{id}/modify    — 修改後確認
  POST /agent/review/batch-approve  — 批量核准

  GET  /agent/batches         — 批次處理歷史
  POST /agent/batches/trigger — 立即觸發批次處理
"""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.config import settings
from app.models.watch_folder import WatchFolder
from app.agent.review_queue import ReviewQueueManager

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Pydantic schemas ────────────────────────────────────────────────────────────

class WatchFolderCreate(BaseModel):
    folder_path: str
    display_name: Optional[str] = None
    recursive: bool = True
    max_depth: int = 10
    default_category: Optional[str] = None


class WatchFolderOut(BaseModel):
    id: str
    folder_path: str
    display_name: Optional[str]
    is_active: bool
    recursive: bool
    last_scan_at: Optional[datetime]
    total_files_watched: int

    model_config = {"from_attributes": True}


class ReviewItemOut(BaseModel):
    id: str
    file_name: str
    file_path: str
    file_ext: Optional[str]
    file_size: Optional[int]
    suggested_category: Optional[str]
    suggested_subcategory: Optional[str]
    suggested_tags: Optional[dict]
    confidence_score: Optional[float]
    reasoning: Optional[str]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ApproveRequest(BaseModel):
    pass  # no body needed


class RejectRequest(BaseModel):
    reason: str = ""


class ModifyRequest(BaseModel):
    category: Optional[str] = None
    tags: Optional[dict] = None
    note: Optional[str] = None


class BatchApproveRequest(BaseModel):
    item_ids: List[str]


class SubfolderScanItem(BaseModel):
    """Frontend 傳來的子資料夾資訊。"""
    path: str = Field(..., max_length=500)         # e.g. "Contracts/2024/Q1"
    name: str = Field(..., max_length=200)         # e.g. "Q1" (最後一段名稱)
    files: List[str] = Field(..., max_length=500)  # 檔名清單（不含路徑）
    content_samples: List[str] = Field(
        default=[],
        max_length=5,
        description="前端讀取的文字檔節錄（頭/中/尾取樣，每份最多 800 字）",
    )


class ScanPreviewRequest(BaseModel):
    subfolders: List[SubfolderScanItem] = Field(..., max_length=100)


# ── Helper ──────────────────────────────────────────────────────────────────────

def _admin_only(current_user):
    if current_user.role not in ("admin", "owner") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="管理員權限才能操作 Agent")


def _folder_out(f: WatchFolder) -> dict:
    return {
        "id": str(f.id),
        "folder_path": f.folder_path,
        "display_name": f.display_name,
        "is_active": f.is_active,
        "recursive": f.recursive,
        "last_scan_at": f.last_scan_at.isoformat() if f.last_scan_at else None,
        "total_files_watched": f.total_files_watched or 0,
    }


def _review_out(item) -> dict:
    tags = dict(item.suggested_tags) if item.suggested_tags else {}
    related = tags.pop("_related_ids", []) if isinstance(tags, dict) else []
    return {
        "id": str(item.id),
        "file_name": item.file_name,
        "file_path": item.file_path,
        "file_ext": item.file_ext,
        "file_size": item.file_size,
        "suggested_category": item.suggested_category,
        "suggested_subcategory": item.suggested_subcategory,
        "suggested_tags": tags,
        "confidence_score": item.confidence_score,
        "reasoning": item.reasoning,
        "status": item.status,
        "related_documents": related,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


# ── Status ──────────────────────────────────────────────────────────────────────

@router.get("/status")
def get_agent_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """取得 Agent 目前運行狀態。"""
    _admin_only(current_user)

    # watcher 狀態
    from app.agent.file_watcher import get_watcher
    w = get_watcher()
    watcher_running = w is not None and w._observer is not None and w._observer.is_alive()

    # 資料夾清單
    folders = db.query(WatchFolder).filter(
        WatchFolder.tenant_id == current_user.tenant_id,
        WatchFolder.is_active == True,
    ).all()

    # 待審核數量
    from app.models.review_item import ReviewItem
    pending_count = db.query(ReviewItem).filter(
        ReviewItem.tenant_id == current_user.tenant_id,
        ReviewItem.status == "pending",
    ).count()

    # 排程狀態
    from app.agent.scheduler import get_scheduler
    s = get_scheduler()
    scheduler_running = (
        s is not None
        and s._scheduler is not None
        and getattr(s._scheduler, "running", False)
    )

    return {
        "watcher_running": watcher_running,
        "scheduler_running": scheduler_running,
        "active_folders": len(folders),
        "pending_review_count": pending_count,
    }


# ── Watch Folders ────────────────────────────────────────────────────────────────

@router.get("/folders")
def list_watch_folders(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """列出已設定的監控資料夾。"""
    _admin_only(current_user)
    folders = db.query(WatchFolder).filter(
        WatchFolder.tenant_id == current_user.tenant_id
    ).order_by(WatchFolder.created_at.desc()).all()
    return [_folder_out(f) for f in folders]


@router.post("/folders", status_code=status.HTTP_201_CREATED)
def add_watch_folder(
    payload: WatchFolderCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """新增監控資料夾。"""
    _admin_only(current_user)

    # 避免重複
    existing = db.query(WatchFolder).filter(
        WatchFolder.tenant_id == current_user.tenant_id,
        WatchFolder.folder_path == payload.folder_path,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="此資料夾路徑已設定監控")

    folder = WatchFolder(
        tenant_id=current_user.tenant_id,
        folder_path=payload.folder_path,
        display_name=payload.display_name,
        recursive=payload.recursive,
        max_depth=payload.max_depth,
        default_category=payload.default_category,
        is_active=True,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)

    # 通知 watcher 重新掃描（新資料夾下次 restart/scan 時生效）
    try:
        from app.agent.file_watcher import get_watcher
        w = get_watcher()
        if w:
            w.watch_folders.append(__import__("pathlib").Path(payload.folder_path))
    except Exception:
        pass

    return _folder_out(folder)


# ── Directory Browser ──────────────────────────────────────────────────────────

@router.get("/browse")
def browse_directories(
    path: str = Query(default="", description="要列出子目錄的路徑；空字串 = 根目錄 / 磁碟機"),
    current_user=Depends(get_current_active_user),
):
    """瀏覽伺服器端目錄結構，供前端資料夾選擇器使用。

    Returns:
      {
        "current": "/absolute/path",
        "parent": "/parent" | null,
        "dirs": [{"name": "foo", "path": "/absolute/path/foo"}, ...]
      }
    """
    _admin_only(current_user)

    # Windows：空路徑 → 列出所有磁碟機
    if not path.strip():
        if os.name == "nt":
            import string
            drives = [
                {"name": f"{d}:\\", "path": f"{d}:\\"}
                for d in string.ascii_uppercase
                if Path(f"{d}:\\").exists()
            ]
            return {"current": "", "parent": None, "dirs": drives}
        else:
            path = "/"

    target = Path(path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="路徑不存在或不是目錄")

    parent = str(target.parent) if target.parent != target else None

    dirs: list[dict] = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: e.name.lower()):
            if entry.is_dir() and not entry.name.startswith("."):
                dirs.append({"name": entry.name, "path": str(entry)})
    except PermissionError:
        pass  # 無權限的資料夾直接跳過

    return {"current": str(target), "parent": parent, "dirs": dirs}


@router.post("/pick-local-folder")
def pick_local_folder(current_user=Depends(get_current_active_user)):
    """開啟作業系統原生資料夾選擇視窗並回傳絕對路徑。"""
    _admin_only(current_user)

    # 主要場景：Windows 本機部署
    if os.name == "nt":
        session_name = (os.environ.get("SESSIONNAME") or "").lower()
        if "service" in session_name:
            raise HTTPException(
                status_code=503,
                detail="後端目前在非互動桌面會話，無法開啟原生資料夾視窗。",
            )

        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$dialog.Description = '請選擇要監控的本機資料夾';"
            "$dialog.ShowNewFolderButton = $false;"
            "$result = $dialog.ShowDialog();"
            "if ($result -eq [System.Windows.Forms.DialogResult]::OK) {"
            "  Write-Output $dialog.SelectedPath"
            "}"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            selected = (proc.stdout or "").strip()
            if not selected:
                return {"selected": False, "path": None}
            return {"selected": True, "path": selected}
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=408, detail="開啟資料夾視窗逾時（20秒）")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"開啟資料夾視窗失敗：{exc}")

    # 非 Windows 的簡易 fallback（需要 GUI 環境）
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        selected = filedialog.askdirectory(title="請選擇要監控的本機資料夾")
        root.destroy()

        if not selected:
            return {"selected": False, "path": None}
        return {"selected": True, "path": selected}
    except Exception as exc:
        raise HTTPException(status_code=501, detail=f"此環境不支援原生資料夾選擇器：{exc}")


# ── Scan Preview (Ollama 資料夾摘要) ────────────────────────────────────────────────

async def _ollama_summarize_folder(
    name: str,
    path: str,
    files: List[str],
    ollama_url: str,
    model: str,
    content_samples: List[str] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> str:
    """Call local Ollama to generate a summary of a folder.
    If content_samples are provided (head/mid/tail text snippets from actual files),
    the summary will be richer and more accurate than filename-only analysis.
    """
    file_sample = files[:40]
    file_list = "\n".join(f"  - {f}" for f in file_sample)
    extra = f"\n  ... 及 {len(files) - len(file_sample)} 個其他檔案" if len(files) > len(file_sample) else ""

    # Build optional content section from actual file snippets (with safety delimiters)
    content_section = ""
    if content_samples:
        content_section = "\n\n【實際檔案內容節錄（前端頭/中/尾取樣）】\n"
        for i, sample in enumerate(content_samples[:3], 1):
            trimmed = sample.strip()[:800]
            if trimmed:
                content_section += f"\n<user_file_excerpt id={i}>\n{trimmed}\n</user_file_excerpt>\n"

    has_content = bool(content_section)
    output_instruction = (
        "用「繁體中文」寫 2\uff5e4 句詳細描述，說明此資料夾存放什麼類型的內容、涵蓋哪些主題或用途。"
        if has_content else
        "用「繁體中文」寫 1\uff5e2 句簡明概述，說明此資料夾存放什麼類型的內容。"
    )

    prompt = (
        "你是一位文件整理助手。"
        f"根據以下資料夾資訊，{output_instruction}"
        "只需輸出概述說明，不需要任何前言、標題或符號。\n\n"
        f"資料夾路徑：{path}\n"
        f"資料夾名稱：{name}\n"
        f"檔案數量：{len(files)}\n"
        f"檔案名稱清單：\n{file_list}{extra}"
        f"{content_section}"
    )

    num_predict = 250 if has_content else 120

    try:
        async def _do_request(c: httpx.AsyncClient) -> str:
            resp = await c.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": num_predict},
                },
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()

        if http_client:
            return await _do_request(http_client)
        else:
            async with httpx.AsyncClient(timeout=90.0) as http:
                return await _do_request(http)
    except httpx.TimeoutException:
        return "（摘要連線逾時）"
    except Exception as exc:
        logger.warning("[ScanPreview] Ollama 摘要失敗 %s: %s", path, exc)
        return "（摘要失敗，可能 Ollama 未啟動）"


@router.post("/scan-preview")
async def scan_preview_folders(
    payload: ScanPreviewRequest,
    current_user=Depends(get_current_active_user),
):
    """接收子資料夾檔名清單，用 Ollama 產生摘要，供前端確認頁使用。"""
    _admin_only(current_user)

    ollama_url: str = getattr(settings, "OLLAMA_SCAN_URL", "http://host.docker.internal:11434")
    model: str = getattr(settings, "OLLAMA_SCAN_MODEL", "gemma3:27b")

    results: List[dict] = []
    async with httpx.AsyncClient(timeout=90.0) as http_client:
        for sf in payload.subfolders:
            has_content = bool(sf.content_samples)
            summary = await _ollama_summarize_folder(
                sf.name, sf.path, sf.files, ollama_url, model,
                content_samples=sf.content_samples if has_content else None,
                http_client=http_client,
            )
            results.append({
                "path": sf.path,
                "name": sf.name,
                "file_count": len(sf.files),
                "summary": summary,
                "has_content_samples": has_content,
            })
            logger.info(
                "[ScanPreview] 完成 %s (%d 個檔案, 內容取樣=%s)",
                sf.path, len(sf.files), "是" if has_content else "否"
            )

    return {"subfolders": results}


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watch_folder(
    folder_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """移除監控資料夾設定。"""
    _admin_only(current_user)
    folder = db.query(WatchFolder).filter(
        WatchFolder.id == folder_id,
        WatchFolder.tenant_id == current_user.tenant_id,
    ).first()
    if not folder:
        raise HTTPException(status_code=404, detail="找不到此資料夾設定")
    db.delete(folder)
    db.commit()


@router.patch("/folders/{folder_id}/toggle")
def toggle_watch_folder(
    folder_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """切換資料夾啟用/停用。"""
    _admin_only(current_user)
    folder = db.query(WatchFolder).filter(
        WatchFolder.id == folder_id,
        WatchFolder.tenant_id == current_user.tenant_id,
    ).first()
    if not folder:
        raise HTTPException(status_code=404, detail="找不到此資料夾設定")
    folder.is_active = not folder.is_active
    db.commit()
    return _folder_out(folder)


# ── Scan / Start / Stop ──────────────────────────────────────────────────────────

@router.post("/scan")
def trigger_scan(current_user=Depends(get_current_active_user)):
    """手動立即觸發掃描。"""
    _admin_only(current_user)
    from app.agent.scheduler import get_scheduler
    scheduler = get_scheduler()
    if scheduler is None:
        raise HTTPException(
            status_code=503,
            detail="排程器尚未啟動，請先啟動 Agent（POST /agent/start）",
        )
    try:
        scheduler.trigger_immediate()
        return {"triggered": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"觸發掃描失敗：{exc}")


@router.post("/start")
def start_agent(current_user=Depends(get_current_active_user)):
    """啟動 Agent 監控。"""
    _admin_only(current_user)
    try:
        from app.agent.file_watcher import start_agent_watcher
        from app.agent.scheduler import start_agent_scheduler
        start_agent_watcher()
        start_agent_scheduler()
        return {"started": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/stop")
def stop_agent(current_user=Depends(get_current_active_user)):
    """停止 Agent 監控。"""
    _admin_only(current_user)
    try:
        from app.agent.file_watcher import stop_agent_watcher
        from app.agent.scheduler import stop_agent_scheduler
        stop_agent_watcher()
        stop_agent_scheduler()
        return {"stopped": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Review Queue ─────────────────────────────────────────────────────────────────

@router.get("/review")
def get_review_queue(
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """取得待審核清單（支援信心度、狀態篩選）。"""
    if current_user.role not in ("admin", "owner", "manager") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理員或審核員權限")

    mgr = ReviewQueueManager(db)
    items, total = mgr.get_pending_items(
        tenant_id=current_user.tenant_id,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_review_out(i) for i in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/review/{item_id}/approve")
def approve_item(
    item_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """核准單一審核項目，觸發向量化。"""
    _admin_only(current_user)
    from app.models.review_item import ReviewItem as RI
    item = db.query(RI).filter(RI.id == item_id).first()
    if item and str(item.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="無權操作其他組織的項目")
    mgr = ReviewQueueManager(db)
    ok = mgr.approve(uuid.UUID(item_id), current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="找不到可核准的項目")
    return {"approved": True, "item_id": item_id}


@router.post("/review/{item_id}/reject")
def reject_item(
    item_id: str,
    payload: RejectRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """拒絕單一審核項目。"""
    _admin_only(current_user)
    from app.models.review_item import ReviewItem as RI
    item = db.query(RI).filter(RI.id == item_id).first()
    if item and str(item.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="無權操作其他組織的項目")
    mgr = ReviewQueueManager(db)
    ok = mgr.reject(uuid.UUID(item_id), payload.reason, current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="找不到項目")
    return {"rejected": True, "item_id": item_id}


@router.post("/review/{item_id}/modify")
def modify_item(
    item_id: str,
    payload: ModifyRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """修改分類後確認入庫。"""
    _admin_only(current_user)
    from app.models.review_item import ReviewItem as RI
    item = db.query(RI).filter(RI.id == item_id).first()
    if item and str(item.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="無權操作其他組織的項目")
    mgr = ReviewQueueManager(db)
    corrections = {k: v for k, v in payload.model_dump().items() if v is not None}
    ok = mgr.modify_and_approve(uuid.UUID(item_id), corrections, current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="找不到項目")
    return {"modified": True, "item_id": item_id}


@router.post("/review/batch-approve")
def batch_approve(
    payload: BatchApproveRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """批量核准多個項目。"""
    _admin_only(current_user)
    mgr = ReviewQueueManager(db)
    count = mgr.batch_approve(
        [uuid.UUID(i) for i in payload.item_ids],
        current_user.id,
    )
    return {"approved_count": count, "total_requested": len(payload.item_ids)}


# ── Batches ──────────────────────────────────────────────────────────────────────

@router.get("/batches")
def list_batches(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """取得近期批次處理狀態統計。"""
    _admin_only(current_user)
    from app.models.review_item import ReviewItem
    from sqlalchemy import func

    counts = db.query(
        ReviewItem.status,
        func.count(ReviewItem.id).label("cnt"),
    ).filter(
        ReviewItem.tenant_id == current_user.tenant_id
    ).group_by(ReviewItem.status).all()

    summary = {r.status: r.cnt for r in counts}
    return {"status_summary": summary}


@router.post("/batches/trigger")
def trigger_batch(current_user=Depends(get_current_active_user)):
    """手動觸發批次重建索引。"""
    _admin_only(current_user)
    from app.agent.scheduler import get_scheduler
    scheduler = get_scheduler()
    if scheduler is None:
        raise HTTPException(
            status_code=503,
            detail="排程器尚未啟動，請先啟動 Agent（POST /agent/start）",
        )
    try:
        scheduler.trigger_immediate()
        return {"triggered": True, "triggered_at": datetime.now(UTC).isoformat()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/batches/report")
def download_batch_report(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """P10-16: 下載批次處理完成報告 PDF。"""
    _admin_only(current_user)
    import io
    from datetime import datetime as dt
    from fastapi.responses import Response
    from app.models.review_item import ReviewItem as RI
    from sqlalchemy import func as sqlfunc

    tid = current_user.tenant_id

    counts_q = (
        db.query(RI.status, sqlfunc.count(RI.id).label("cnt"))
        .filter(RI.tenant_id == tid)
        .group_by(RI.status)
        .all()
    )
    summary = {r.status: r.cnt for r in counts_q}
    total = sum(summary.values())

    # Recent indexed items
    recent = (
        db.query(RI.file_name, RI.suggested_category, RI.indexed_at)
        .filter(RI.tenant_id == tid, RI.status == "indexed")
        .order_by(RI.indexed_at.desc())
        .limit(20)
        .all()
    )

    # Build PDF with reportlab
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.units import mm
    except ImportError:
        raise HTTPException(status_code=500, detail="reportlab not installed")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=20*mm, rightMargin=20*mm,
                             topMargin=20*mm, bottomMargin=20*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=16, spaceAfter=6)
    head_style = ParagraphStyle("Head", parent=styles["Heading2"], fontSize=12, spaceAfter=4)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9, leading=14)

    status_label = {
        "pending": "待審核", "approved": "已核准", "modified": "修改確認",
        "rejected": "已拒絕", "processing": "向量化中", "indexed": "已入庫", "failed": "失敗",
    }

    now_str = dt.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    story = [
        Paragraph("批次處理完成報告", title_style),
        Paragraph(f"產生時間：{now_str}", body_style),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=0.5, color=colors.grey),
        Spacer(1, 8),
        Paragraph("審核佇列狀態統計", head_style),
    ]

    # Status table
    tdata = [["狀態", "數量", "佔比"]]
    for st, cnt in sorted(summary.items(), key=lambda x: -x[1]):
        pct = f"{round(cnt / total * 100)}%" if total else "0%"
        tdata.append([status_label.get(st, st), str(cnt), pct])
    tdata.append(["合計", str(total), "100%"])

    tbl = Table(tdata, colWidths=[60*mm, 30*mm, 30*mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 12))

    if recent:
        story.append(Paragraph("最近入庫文件（最多 20 筆）", head_style))
        rddata = [["檔案名稱", "分類", "入庫時間"]]
        for r in recent:
            rddata.append([
                r.file_name[:60],
                r.suggested_category or "—",
                r.indexed_at.strftime("%Y-%m-%d %H:%M") if r.indexed_at else "—",
            ])
        rtbl = Table(rddata, colWidths=[90*mm, 40*mm, 40*mm])
        rtbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ]))
        story.append(rtbl)

    doc.build(story)
    buf.seek(0)
    filename = f"batch_report_{dt.utcnow().strftime('%Y%m%d_%H%M')}.pdf"
    return Response(
        content=buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
