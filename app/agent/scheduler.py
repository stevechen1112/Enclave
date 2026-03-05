"""
Phase 10 — 排程批次處理器 (Scheduler)  [P10-2 實作]

使用 APScheduler 管理每日索引重建任務：
  - 每日凌晨 AGENT_BATCH_HOUR 時執行全量掃描（catch-up）
  - CPU 使用率上限保護（避免影響日常使用）
  - 可手動觸發立即重建

排程設計：
  scheduled  — 每日固定時間執行（APScheduler CronTrigger）
  immediate  — 手動觸發（API 呼叫或管理後台按鈕）
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BatchReport:
    """每次批次重建結束後的完成報告。"""
    batch_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    total_queued: int = 0
    total_indexed: int = 0
    total_failed: int = 0
    total_skipped: int = 0
    failed_files: list = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_queued == 0:
            return 0.0
        return self.total_indexed / self.total_queued


# ─────────────────────────────────────────────────────────────
# BatchScheduler
# ─────────────────────────────────────────────────────────────

class BatchScheduler:
    """
    APScheduler 驅動的批次索引排程器。

    啟動後每天在 batch_hour 點執行一次全量 catch-up 掃描：
    掃描所有 watch folders，將 mtime > 上次索引時間的檔案重新佇列。
    """

    def __init__(self, max_cpu_percent: float = 50.0, batch_hour: int = 2) -> None:
        self.max_cpu_percent = max_cpu_percent
        self.batch_hour = batch_hour
        self._scheduler = None  # 延遲初始化，避免 import 時就載入 APScheduler

    def start_scheduled_job(self) -> None:
        """啟動 APScheduler 並註冊每日重建 Job。"""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.warning("[Scheduler] apscheduler 未安裝，排程批次處理已停用")
            return

        self._scheduler = BackgroundScheduler(
            job_defaults={"misfire_grace_time": 3600}  # 錯過執行時允許 1h 延遲補跑
        )
        self._scheduler.add_job(
            func=self._run_daily_rebuild,
            trigger=CronTrigger(hour=self.batch_hour, minute=0),
            id="daily_rebuild",
            name="每日知識庫重建",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            f"[Scheduler] 排程已啟動，每日 {self.batch_hour:02d}:00 執行全量重建"
        )

    def stop(self) -> None:
        """停止排程器。"""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("[Scheduler] 排程已停止")
        self._scheduler = None

    def trigger_immediate(self) -> str:
        """手動立即觸發全量重建，回傳 batch_id。"""
        import uuid
        batch_id = str(uuid.uuid4())[:8]
        logger.info(f"[Scheduler] 手動觸發立即重建 (batch={batch_id})")
        self._run_daily_rebuild(batch_id=batch_id)
        return batch_id

    # ─── 內部執行邏輯 ───

    def _check_cpu(self) -> bool:
        """檢查 CPU 使用率，超限時回傳 False（讓任務等待）。"""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=1)
            if cpu > self.max_cpu_percent:
                logger.warning(
                    f"[Scheduler] CPU 使用率 {cpu:.0f}% 超過上限 "
                    f"{self.max_cpu_percent:.0f}%，批次暫緩"
                )
                return False
        except ImportError:
            pass  # psutil 未安裝，略過 CPU 檢查
        return True

    def _run_daily_rebuild(self, batch_id: Optional[str] = None) -> None:
        """
        實際執行邏輯：
        1. 檢查 CPU 使用率
        2. 取得 AGENT_WATCH_FOLDERS
        3. 觸發 watcher_ingest_file_task（skip_if_current=True）
        """
        import uuid as _uuid
        if not batch_id:
            batch_id = str(_uuid.uuid4())[:8]

        try:
            from app.config import settings

            if not self._check_cpu():
                logger.warning("[Scheduler] CPU 超限，本次批次跳過")
                return

            folders_str = getattr(settings, "AGENT_WATCH_FOLDERS", "")
            if not folders_str.strip():
                logger.info("[Scheduler] 未設定監控資料夾，批次跳過")
                return

            # 重用 FolderWatcher.initial_scan 邏輯
            from app.agent.file_watcher import FolderWatcher
            folders = [f.strip() for f in folders_str.split(",") if f.strip()]
            watcher = FolderWatcher(folders)
            queued = watcher.initial_scan()
            logger.info(
                f"[Scheduler] 批次重建完成 (batch={batch_id})，已佇列 {queued} 個檔案"
            )
        except Exception as exc:
            logger.error(f"[Scheduler] 批次重建失敗 (batch={batch_id}): {exc}")


# ─────────────────────────────────────────────────────────────
# 全局單例管理（供 main.py lifespan 呼叫）
# ─────────────────────────────────────────────────────────────

_scheduler: Optional[BatchScheduler] = None


def get_scheduler() -> Optional[BatchScheduler]:
    return _scheduler


def start_agent_scheduler() -> None:
    """從應用啟動（lifespan）呼叫，啟動排程批次重建。"""
    global _scheduler
    try:
        from app.config import settings
        _scheduler = BatchScheduler(
            max_cpu_percent=settings.AGENT_MAX_CPU_PERCENT,
            batch_hour=settings.AGENT_BATCH_HOUR,
        )
        _scheduler.start_scheduled_job()
    except Exception as exc:
        logger.error(f"[Scheduler] 啟動失敗: {exc}")


def stop_agent_scheduler() -> None:
    """從應用關閉（lifespan）呼叫，停止排程器。"""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
        _scheduler = None
