"""Tenant-scoped persistence for core voice interaction sessions.

Voice capture is an Input capability, so it must not depend on an optional
training application pack.  This repository deliberately owns only the
generic interaction lifecycle used by the core voice API.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.mka import InteractionSession
from app.services.workflow_repository import WorkflowConflictError, WorkflowNotFoundError


InteractionNotFoundError = WorkflowNotFoundError
InteractionConflictError = WorkflowConflictError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def interaction_to_dict(row: InteractionSession) -> Dict[str, Any]:
    return {
        "session_id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "user_id": str(row.user_id),
        "module_key": row.module_key,
        "channel": row.channel,
        "scene_context": row.scene_context or {},
        "transcript": row.transcript,
        "transcript_metadata": row.transcript_metadata or {},
        "transcript_confirmed_at": (
            row.transcript_confirmed_at.isoformat()
            if row.transcript_confirmed_at
            else None
        ),
        "detected_fields": row.detected_fields or {},
        "risk_level": row.risk_level,
        "state": row.state,
    }


class InteractionRepository:
    """Persist generic voice interactions with explicit tenant/user scope."""

    def __init__(self, db: Session):
        self.db = db

    def save_transcript(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        text: str,
        metadata: Dict[str, Any],
        detected_fields: Sequence[Dict[str, Any]],
        session_id: Optional[UUID] = None,
        module_key: Optional[str] = None,
        channel: str = "web",
        scene_context: Optional[Dict[str, Any]] = None,
        risk_level: str = "low",
    ) -> InteractionSession:
        row: Optional[InteractionSession] = None
        if session_id:
            row = self._interaction(tenant_id, user_id, session_id)
            if row.state in {"completed", "expired"}:
                raise InteractionConflictError(f"interaction session is {row.state}")
        if row is None:
            row = InteractionSession(
                tenant_id=tenant_id,
                user_id=user_id,
                module_key=module_key,
                channel=channel,
            )
            self.db.add(row)
        row.transcript = text
        row.transcript_metadata = _copy_json(metadata)
        row.detected_fields = {"fields": _copy_json(list(detected_fields))}
        row.scene_context = _copy_json(scene_context or {})
        row.risk_level = risk_level
        row.transcript_confirmed_at = None
        row.state = "waiting_confirmation"
        self.db.flush()
        return row

    def confirm_transcript(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        session_id: UUID,
        confirmed_text: Optional[str] = None,
        confirmed_fields: Optional[Dict[str, Any]] = None,
    ) -> InteractionSession:
        row = self._interaction(tenant_id, user_id, session_id)
        if row.state in {"completed", "expired"}:
            raise InteractionConflictError(f"interaction session is {row.state}")
        if confirmed_text is not None:
            metadata = dict(row.transcript_metadata or {})
            metadata["draft_transcript"] = row.transcript
            row.transcript_metadata = metadata
            row.transcript = confirmed_text
        detected = dict(row.detected_fields or {})
        fields = []
        confirmed_fields = confirmed_fields or {}
        for item in detected.get("fields", []):
            field = dict(item)
            key = field.get("type")
            if key in confirmed_fields:
                field["confirmed_value"] = confirmed_fields[key]
            field["needs_confirm"] = False
            fields.append(field)
        row.detected_fields = {"fields": fields}
        row.transcript_confirmed_at = _now()
        row.state = "active"
        self.db.flush()
        return row

    def resolve_interaction(
        self, *, tenant_id: UUID, user_id: UUID, session_id: UUID
    ) -> InteractionSession:
        row = self._interaction(tenant_id, user_id, session_id)
        if row.risk_level == "high" and row.transcript_confirmed_at is None:
            raise InteractionConflictError(
                "high-risk transcript must be confirmed before resolve"
            )
        row.state = "completed"
        self.db.flush()
        return row

    def _interaction(
        self, tenant_id: UUID, user_id: UUID, session_id: UUID
    ) -> InteractionSession:
        row = (
            self.db.query(InteractionSession)
            .filter(
                InteractionSession.id == session_id,
                InteractionSession.tenant_id == tenant_id,
                InteractionSession.user_id == user_id,
            )
            .first()
        )
        if row is None:
            raise InteractionNotFoundError("interaction session not found")
        return row
