"""Lifecycle helpers for provider-backed resumable transfer sessions."""
from __future__ import annotations


def cleanup_staging(session) -> None:
    """Remove either an incomplete multipart upload or its completed staging object."""
    from app.services.storage import get_storage_backend

    storage = get_storage_backend()
    # A provider may have completed immediately before a database failure.
    # Existence is therefore authoritative, not the cached completion flag.
    if storage.exists(session.staging_key):
        storage.delete(session.staging_key)
    else:
        storage.abort_multipart(session.staging_key, session.provider_upload_id)


def expire_sessions(db, *, before=None, limit: int = 500) -> int:
    """Expire stale non-terminal sessions; caller owns commit/RLS context."""
    from datetime import datetime, timezone

    from app.models.upload import UploadSession

    threshold = before or datetime.now(timezone.utc)
    rows = (
        db.query(UploadSession)
        .filter(
            UploadSession.status.in_(
                ("initialized", "uploading", "committing", "failed")
            ),
            UploadSession.expires_at <= threshold,
        )
        .order_by(UploadSession.expires_at)
        .limit(max(1, min(limit, 5000)))
        .all()
    )
    for row in rows:
        cleanup_staging(row)
        row.status = "expired"
    return len(rows)
