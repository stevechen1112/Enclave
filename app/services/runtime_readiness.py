"""Fast, non-secret dependency readiness probes used by health and alerting."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def database_readiness() -> bool:
    from app.db.session import readiness_engine
    from app.middleware.metrics import set_dependency_ready

    ready = False
    try:
        with readiness_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        ready = True
    except SQLAlchemyError:
        ready = False
    set_dependency_ready("database", ready)
    return ready
