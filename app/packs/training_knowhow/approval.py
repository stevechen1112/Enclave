"""Know-how approval side effects owned by the training application."""

from datetime import datetime, timezone


def apply_decision(db, approval, *, action: str, reviewer_id, reason: str = "") -> None:
    from app.models.mka import KnowhowCardModel

    row = db.query(KnowhowCardModel).filter(
        KnowhowCardModel.tenant_id == approval.tenant_id,
        KnowhowCardModel.id == approval.object_id,
    ).first()
    if row is None:
        raise ValueError("know-how approval target not found")
    now = datetime.now(timezone.utc)
    if action == "approve":
        row.status = "approved"
        row.effective_from = row.effective_from or now
    elif action == "reject":
        row.status = "rejected"
        row.rejection_reason = reason
    elif action == "request_changes":
        row.status = "changes_requested"
    else:
        raise ValueError(f"unsupported know-how approval action: {action}")
    if reviewer_id is not None:
        row.reviewer = reviewer_id
    row.reviewed_at = now


def task_reference_key() -> str:
    return "knowhow_card_id"
