from celery import Celery
from app.config import settings

# 使用 settings 中的配置，確保從環境變數讀取
celery_app = Celery(
    "unihr",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.broker_connection_retry_on_startup = True

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
