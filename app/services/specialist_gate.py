"""Feature gate: RAGFlow specialist retrieval must stay off until eval passes."""
from __future__ import annotations

import os


SPECIALIST_FLAG = "ragflow_specialist_retrieval"
SPECIALIST_ENV = "RAGFLOW_SPECIALIST_ENABLED"


def specialist_retrieval_enabled(tenant_id: str | None = None) -> bool:
    """
    GA default: False.
    Enable only via RAGFLOW_SPECIALIST_ENABLED=true AND (optional) feature flag.
    """
    if os.getenv(SPECIALIST_ENV, "").lower() != "true":
        return False
    try:
        from app.db.session import SessionLocal
        from app.services.feature_flags import is_flag_enabled
        db = SessionLocal()
        try:
            return bool(is_flag_enabled(db, SPECIALIST_FLAG, tenant_id=tenant_id))
        finally:
            db.close()
    except Exception:
        # Env alone can enable in lab; still default false without env
        return os.getenv(SPECIALIST_ENV, "").lower() == "true"
