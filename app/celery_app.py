from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from celery import Celery
from app.config import settings

# 使用 settings 中的配置，確保從環境變數讀取
celery_app = Celery(
    "enclave",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.broker_connection_retry_on_startup = True
celery_app.conf.broker_connection_retry = True
celery_app.conf.broker_connection_max_retries = 5
celery_app.conf.broker_pool_limit = 3

celery_app.conf.task_routes = {
    "app.tasks.*": {"queue": "celery"}
}

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Auto-discover tasks so that @celery_app.task decorators in app/tasks/ get registered
celery_app.autodiscover_tasks(['app.tasks'])

# Explicitly import tasks to ensure they are registered
import app.tasks.document_tasks  # noqa: F401, E402
import app.tasks.kb_maintenance_tasks  # noqa: F401, E402
import app.tasks.outbox_worker  # noqa: F401, E402
import app.tasks.reconciliation_tasks  # noqa: F401, E402
import app.tasks.connector_tasks  # noqa: F401, E402
import app.tasks.mka_tasks  # noqa: F401, E402

from app.observability.sentry import init_sentry

init_sentry("enclave-worker")

celery_app.conf.beat_schedule = {
    "process-outbox-batch": {
        "task": "tasks.process_outbox",
        "schedule": 5.0,
    },
    "reconcile-projections": {
        "task": "tasks.reconcile_projections",
        "schedule": 300.0,
    },
    "poll-pending-connectors": {
        "task": "tasks.poll_pending_connectors",
        "schedule": 60.0,
    },
    "purge-mka-retention": {
        "task": "tasks.purge_mka_retention",
        "schedule": 86400.0,  # 每日硬刪過期轉寫（§12.1）
    },
    "detect-knowledge-gaps": {
        "task": "tasks.detect_knowledge_gaps",
        "schedule": 86400.0,
        "kwargs": {"days": 7},
    },
    "refresh-knowledge-freshness": {
        "task": "tasks.refresh_knowledge_freshness",
        "schedule": 86400.0,
    },
}
