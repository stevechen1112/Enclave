from __future__ import annotations

import threading
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.services.intake_context import acquire_content_identity_lock


def test_postgres_content_identity_lock_serializes_concurrent_replays(test_engine):
    if test_engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL advisory locks are production-specific")

    factory = sessionmaker(bind=test_engine)
    first = factory()
    second = factory()
    tenant_id = uuid4()
    content_hash = uuid4().hex * 2
    started = threading.Event()
    acquired = threading.Event()
    errors: list[BaseException] = []

    try:
        acquire_content_identity_lock(
            first, tenant_id=tenant_id, content_hash=content_hash
        )

        def acquire_second() -> None:
            try:
                started.set()
                acquire_content_identity_lock(
                    second, tenant_id=tenant_id, content_hash=content_hash
                )
                acquired.set()
                second.commit()
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        worker = threading.Thread(target=acquire_second, daemon=True)
        worker.start()
        assert started.wait(timeout=1)
        assert not acquired.wait(timeout=0.25)

        first.commit()
        assert acquired.wait(timeout=2)
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert errors == []
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
