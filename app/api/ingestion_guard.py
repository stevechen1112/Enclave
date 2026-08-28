"""HTTP boundary for P5 ingestion queue saturation."""

from fastapi import HTTPException, status

from app.config import settings
from app.services.queue_guardrails import check_queue_capacity


def enforce_ingestion_queue_capacity() -> None:
    result = check_queue_capacity()
    if result["allowed"]:
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "queue_saturated",
            "message": "處理佇列目前已滿，資料尚未接收，請稍後重試",
            "depth": result["depth"],
            "limit": result["limit"],
        },
        headers={"Retry-After": str(settings.QUEUE_GUARD_RETRY_AFTER_SECONDS)},
    )
