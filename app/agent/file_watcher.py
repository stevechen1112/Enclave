"""
Phase 10 — 資料夾監控 Agent (File Watcher)  [P10-1 實作]

使用 watchdog 套件監控指定本機資料夾。
有新增或修改的檔案時，自動觸發 Celery 索引任務（parse + embed）。

支援：
  - 多資料夾同時監控（AGENT_WATCH_FOLDERS 逗號分隔）
  - 遞迴子資料夾掃描（recursive=True）
  - 副檔名過濾（沿用 document_parser.py 支援格式）
  - 防抖動 (debounce 5s)：同一檔案短時間內多次事件只觸發一次
  - 移動事件（舊路徑=刪除，新路徑=新增）
  - 首次啟動全量掃描，僅佇列未索引或已過期的檔案
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.config import settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# 防抖等待時間（秒）—— 避免檔案尚未寫完就觸發索引
DEBOUNCE_SECONDS = 5.0

# 支援的副檔名（與 document_parser.py 一致）
SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls",
    ".csv", ".html", ".htm", ".md", ".rtf", ".json",
    ".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".pptx", ".ppt",
}


# ─────────────────────────────────────────────────────────────
# 取得預設租戶 / 用戶（地端單一組織模式）
# ─────────────────────────────────────────────────────────────

def _get_default_tenant_and_user() -> Tuple[Optional[str], Optional[str]]:
    """從 DB 取得預設 tenant_id 和 admin user_id。"""
    db = SessionLocal()
    try:
        from app.models.tenant import Tenant
        from app.models.user import User

        tenant = db.query(Tenant).filter(Tenant.status == "active").first()
        if not tenant:
            logger.warning("[Agent] 找不到 active tenant，無法啟動 file watcher")
            return None, None

        user = (
            db.query(User)
            .filter(User.tenant_id == tenant.id, User.role == "admin")
            .first()
        )
        if not user:
            # fallback：取任意屬於此 tenant 的用戶
            user = db.query(User).filter(User.tenant_id == tenant.id).first()
        if not user:
            logger.warning("[Agent] 找不到系統用戶，無法建立文件記錄")
            return str(tenant.id), None

        return str(tenant.id), str(user.id)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────
# watchdog 事件處理器（含防抖）
# ─────────────────────────────────────────────────────────────

class _FileChangeHandler(FileSystemEventHandler):
    """接收 watchdog 事件，防抖後觸發 Celery 任務。"""

    def __init__(self, tenant_id: str, user_id: str) -> None:
        super().__init__()
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._pending: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    # ── 防抖邏輯 ──

    def _schedule(self, path: str, event_type: str) -> None:
        """為此路徑設定（或重設）防抖計時器。"""
        with self._lock:
            existing = self._pending.pop(path, None)
            if existing:
                existing.cancel()
            timer = threading.Timer(
                DEBOUNCE_SECONDS, self._fire, args=(path, event_type)
            )
            timer.daemon = True
            self._pending[path] = timer
            timer.start()

    def _fire(self, path: str, event_type: str) -> None:
        """防抖期滿，真正觸發 Celery 任務。"""
        with self._lock:
            self._pending.pop(path, None)
        try:
            from app.tasks.document_tasks import (
                watcher_delete_file_task,
                watcher_ingest_file_task,
            )

            if event_type == "delete":
                logger.info(f"[Agent] 偵測刪除：{path}")
                watcher_delete_file_task.delay(path, self.tenant_id)
            else:
                if not Path(path).exists():
                    # 可能是臨時檔或已被移走
                    return
                logger.info(f"[Agent] 偵測 {event_type}：{path}")
                watcher_ingest_file_task.delay(path, self.tenant_id, self.user_id)
        except Exception as exc:
            logger.error(f"[Agent] 觸發任務失敗 {path}: {exc}")

    # ── 副檔名過濾 ──

    @staticmethod
    def _supported(path: str) -> bool:
        return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS

    # ── watchdog 回呼 ──

    def on_created(self, event) -> None:
        if not event.is_directory and self._supported(event.src_path):
            self._schedule(event.src_path, "created")

    def on_modified(self, event) -> None:
        if not event.is_directory and self._supported(event.src_path):
            self._schedule(event.src_path, "modified")

    def on_deleted(self, event) -> None:
        if not event.is_directory and self._supported(event.src_path):
            self._schedule(event.src_path, "delete")

    def on_moved(self, event) -> None:
        if not event.is_directory:
            if self._supported(event.src_path):
                self._schedule(event.src_path, "delete")
            if self._supported(event.dest_path):
                self._schedule(event.dest_path, "created")


# ─────────────────────────────────────────────────────────────
# FolderWatcher — 主要對外介面
# ─────────────────────────────────────────────────────────────

class FolderWatcher:
    """監控多個資料夾，有檔案異動時觸發知識庫索引任務。"""

    def __init__(self, watch_folders: List[str]) -> None:
        self.watch_folders = [Path(f.strip()) for f in watch_folders if f.strip()]
        self._observer: Optional[Observer] = None
        self._tenant_id: Optional[str] = None
        self._user_id: Optional[str] = None

    # ── 內部輔助 ──

    def _ensure_tenant(self) -> bool:
        """讀取（或刷新）預設 tenant / user ID，回傳是否成功。"""
        self._tenant_id, self._user_id = _get_default_tenant_and_user()
        if not self._tenant_id or not self._user_id:
            return False
        return True

    # ── 公開介面 ──

    def start(self) -> bool:
        """啟動資料夾監控（背景執行緒）。回傳是否成功啟動。"""
        if not self.watch_folders:
            logger.info("[Agent] 沒有設定監控資料夾，跳過啟動")
            return False
        if not self._ensure_tenant():
            return False

        handler = _FileChangeHandler(self._tenant_id, self._user_id)
        self._observer = Observer()

        activated = 0
        for folder in self.watch_folders:
            if not folder.exists():
                logger.warning(f"[Agent] 監控資料夾不存在，跳過：{folder}")
                continue
            self._observer.schedule(handler, str(folder), recursive=True)
            logger.info(f"[Agent] 監控中：{folder}")
            activated += 1

        if activated == 0:
            logger.warning("[Agent] 所有監控資料夾均不存在，監控未啟動")
            return False

        self._observer.start()
        logger.info(f"[Agent] 檔案監控已啟動（{activated} 個資料夾，防抖 {DEBOUNCE_SECONDS}s）")
        return True

    def stop(self) -> None:
        """停止監控（應用關閉時呼叫）。"""
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join(timeout=5)
            logger.info("[Agent] 監控已停止")
        self._observer = None

    def initial_scan(self) -> int:
        """
        首次全量掃描：將所有監控資料夾中的現有檔案佇列至索引任務。
        已索引且 mtime 未更新的檔案會被跳過（skip_if_current=True）。
        回傳送出的任務數。
        """
        if not self._ensure_tenant():
            return 0

        from app.tasks.document_tasks import watcher_ingest_file_task

        queued = 0
        for folder in self.watch_folders:
            if not folder.exists():
                continue
            for path in folder.rglob("*"):
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    try:
                        watcher_ingest_file_task.delay(
                            str(path),
                            self._tenant_id,
                            self._user_id,
                            skip_if_current=True,
                        )
                        queued += 1
                    except Exception as exc:
                        logger.error(f"[Agent] 初始掃描任務佇列失敗 {path}: {exc}")

        logger.info(f"[Agent] 初始掃描完成，已送出 {queued} 個任務")
        return queued


# ─────────────────────────────────────────────────────────────
# 全局單例管理（供 main.py lifespan 呼叫）
# ─────────────────────────────────────────────────────────────

_watcher: Optional[FolderWatcher] = None


def get_watcher() -> Optional[FolderWatcher]:
    return _watcher


def start_agent_watcher() -> None:
    """從應用啟動（lifespan）呼叫，啟動 file watcher 和初始掃描。"""
    global _watcher

    if not settings.AGENT_WATCH_ENABLED:
        logger.info("[Agent] 資料夾監控已停用（AGENT_WATCH_ENABLED=false）")
        return

    folders = [f.strip() for f in settings.AGENT_WATCH_FOLDERS.split(",") if f.strip()]
    if not folders:
        logger.info("[Agent] 未設定監控資料夾（AGENT_WATCH_FOLDERS 為空）")
        return

    _watcher = FolderWatcher(folders)
    started = _watcher.start()
    if started:
        # 延遲 15 秒後執行首次掃描（等 DB / Celery 連線就緒）
        timer = threading.Timer(15.0, _watcher.initial_scan)
        timer.daemon = True
        timer.start()


def stop_agent_watcher() -> None:
    """從應用關閉（lifespan）呼叫，停止 file watcher。"""
    global _watcher
    if _watcher:
        _watcher.stop()
        _watcher = None
