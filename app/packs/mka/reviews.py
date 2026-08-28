"""MKA review provider for the source-neutral platform workspace."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.mka import ApprovalPolicy, KnowhowCardModel, MKAApprovalRequest
from app.models.user import User
from app.services.mka_persistence import MKARepository


class MKAReviewProvider:
    provider_key = "mka.knowledge_review"
    item_prefix = "knowhow"

    @staticmethod
    def _blocked(
        card: KnowhowCardModel,
        approval: MKAApprovalRequest,
        policy: ApprovalPolicy | None,
        current_user: User,
    ) -> list[str]:
        blocked: list[str] = []
        if approval.submitted_by == current_user.id:
            blocked.append("separation_of_duty")
        if policy is None or policy.status != "active":
            blocked.append("approval_policy_missing")
        if approval.expires_at is not None and approval.expires_at <= datetime.now(UTC):
            blocked.append("approval_policy_expired")
        if any(not row.get("resolved") for row in (card.conflict_report or [])):
            blocked.append("unresolved_sop_conflicts")
        required = {str(role) for role in (approval.reviewers or [])}
        if (
            required
            and not current_user.is_superuser
            and current_user.role not in required
        ):
            blocked.append("reviewer_role_not_allowed")
        return blocked

    def list_items(self, *, db: Session, current_user: User) -> list[dict[str, Any]]:
        rows = (
            db.query(MKAApprovalRequest, KnowhowCardModel, ApprovalPolicy)
            .join(
                KnowhowCardModel,
                (KnowhowCardModel.tenant_id == MKAApprovalRequest.tenant_id)
                & (KnowhowCardModel.id == MKAApprovalRequest.object_id),
            )
            .outerjoin(
                ApprovalPolicy,
                ApprovalPolicy.id == MKAApprovalRequest.approval_policy_id,
            )
            .filter(
                MKAApprovalRequest.tenant_id == current_user.tenant_id,
                MKAApprovalRequest.object_type == "knowhow",
                MKAApprovalRequest.status == "pending",
                KnowhowCardModel.status == "pending_review",
            )
            .order_by(MKAApprovalRequest.created_at.desc())
            .limit(200)
            .all()
        )
        items: list[dict[str, Any]] = []
        for approval, card, policy in rows:
            blocked = self._blocked(card, approval, policy, current_user)
            risk = card.risk_level or "medium"
            evidence = []
            for index, quote in enumerate(card.source_quotes or []):
                evidence.append(
                    {
                        "id": f"knowhow-quote:{card.id}:{index}",
                        "kind": "audio" if card.source_audio_uri else "document",
                        "section": str(quote),
                        "deep_link": f"/knowhow/{card.id}?evidence={index}",
                    }
                )
            if not evidence:
                evidence.append(
                    {
                        "id": f"knowhow:{card.id}",
                        "kind": "document",
                        "section": "知識卡草稿",
                        "deep_link": f"/knowhow/{card.id}",
                    }
                )
            items.append(
                {
                    "id": f"knowhow:{card.id}",
                    "provider": self.provider_key,
                    "source_type": "knowhow_card",
                    "asset_kind": card.source_type or "knowledge_card",
                    "title": card.title,
                    "subtitle": card.summary or "老師傅經驗知識卡",
                    "status": "pending",
                    "risk_level": risk,
                    "confidence": None,
                    "created_at": approval.created_at.isoformat(),
                    "due_at": (
                        approval.expires_at or (approval.created_at + timedelta(days=7))
                    ).isoformat(),
                    "department_ids": [],
                    "policy_key": f"mka:{policy.id}" if policy else "mka:missing",
                    "policy_version": approval.policy_version,
                    "assignee": ", ".join(approval.reviewers or []) or None,
                    "batch_eligible": risk == "low" and not blocked,
                    "blocked_reasons": blocked,
                    "proposal": {
                        "summary": card.summary,
                        "steps": list(card.steps or []),
                        "cautions": list(card.cautions or []),
                        "risks": list(card.risks or []),
                        "prohibited_actions": list(card.prohibited_actions or []),
                        "conflicts": list(card.conflict_report or []),
                        "record_version": approval.record_version,
                    },
                    "evidence": evidence,
                    "publication": {
                        "unit_key": f"knowhow:{card.id}",
                        "next_revision": card.version,
                        "effective_from": "on_final_approval",
                        "acl": {"visibility": "tenant", "policy_revision": 1},
                        "rollback": "retire the KnowledgeUnit and restore the prior release",
                        "sop_precedence": True,
                    },
                }
            )
        return items

    def decide(
        self,
        *,
        db: Session,
        current_user: User,
        object_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        repository = MKARepository(db)
        approval = repository.get_pending_approval_for_object(
            tenant_id=current_user.tenant_id,
            object_type="knowhow",
            object_id=object_id,
        )
        card = repository.get_knowhow(
            tenant_id=current_user.tenant_id, knowhow_id=object_id
        )
        policy = (
            db.query(ApprovalPolicy)
            .filter(ApprovalPolicy.id == approval.approval_policy_id)
            .first()
        )
        if payload["decision"] == "approved" and card.conflict_report:
            resolutions = dict(payload.get("conflict_resolutions") or {})
            known_ids = {
                str(row.get("id") or index)
                for index, row in enumerate(card.conflict_report or [])
                if isinstance(row, dict) and not row.get("resolved")
            }
            unknown = set(resolutions) - known_ids
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "unknown_sop_conflict",
                        "conflict_ids": sorted(unknown),
                    },
                )
            report = []
            for index, row in enumerate(card.conflict_report or []):
                updated = dict(row)
                conflict_id = str(updated.get("id") or index)
                if resolutions.get(conflict_id) == "sop_wins":
                    updated.update({"resolved": True, "resolution": "sop_wins"})
                report.append(updated)
            card.conflict_report = report
        blocked = self._blocked(card, approval, policy, current_user)
        if payload["decision"] == "approved" and blocked:
            raise HTTPException(
                status_code=409,
                detail={"code": blocked[0], "blocked_reasons": blocked},
            )
        if (
            payload["decision"] == "approved"
            and card.risk_level == "high"
            and not payload.get("acknowledge_high_risk")
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "high_risk_acknowledgement_required"},
            )
        idempotency_key = str(payload.get("idempotency_key") or uuid4())
        was_idempotent = any(
            entry.get("idempotency_key") == idempotency_key
            for entry in (approval.decision_log or [])
        )
        decided = repository.decide_approval(
            tenant_id=current_user.tenant_id,
            approval_id=approval.id,
            reviewer_id=current_user.id,
            reviewer_roles=[current_user.role],
            expected_version=approval.record_version,
            idempotency_key=idempotency_key,
            action="approve" if payload["decision"] == "approved" else "reject",
            reason=str(payload.get("notes") or ""),
            is_superuser=bool(current_user.is_superuser),
        )
        authority = None
        if decided.status == "approved":
            from app.services.knowledge_authority import publish_approved_knowhow

            card = repository.get_knowhow(
                tenant_id=current_user.tenant_id, knowhow_id=object_id
            )
            authority = publish_approved_knowhow(
                db, card=card, reviewer_id=current_user.id
            )
        return {
            "item_id": f"knowhow:{object_id}",
            "decision": payload["decision"],
            "approval_status": decided.status,
            "knowledge_authority": authority,
            "idempotent": was_idempotent,
        }
