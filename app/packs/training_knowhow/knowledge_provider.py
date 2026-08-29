"""Approved MKA know-how contribution for the platform knowledge registry."""

from __future__ import annotations

from typing import Any, ClassVar

from app.platform.knowledge.providers import (
    KnowledgeCandidate,
    KnowledgeContributionContext,
)


class ApprovedKnowhowProvider:
    provider_key = "mka.approved_knowhow"
    provider_version = "1.0"
    capability_keys = ("knowledge.knowhow.read",)
    module_key = "training_knowhow"

    _AUTHORITY_MULTIPLIER: ClassVar[dict[int, float]] = {
        100: 1.0,
        90: 0.95,
        80: 0.90,
        70: 0.85,
        60: 0.80,
        20: 0.50,
    }

    def contribute(
        self, context: KnowledgeContributionContext
    ) -> list[KnowledgeCandidate]:
        from app.config import settings

        if not (
            settings.KNOWHOW_CARD_ENABLED
            and settings.KNOWHOW_DRAFT_ISOLATION
            and context.db is not None
        ):
            return []

        # A KB revision is an immutable document manifest. Know-how cards do
        # not yet have revision membership, so including them would violate an
        # explicit scope. Phase B will replace this with KnowledgeUnit release
        # membership rather than silently broadening the query.
        if context.has_explicit_kb_revision_scope:
            return []

        if not self._tenant_module_enabled(context):
            return []

        from app.packs.training_knowhow.persistence import MKARepository

        results: list[KnowledgeCandidate] = []
        for card in MKARepository(context.db).list_approved_knowhow(
            tenant_id=context.authz.tenant_id,
            limit=context.top_k,
        ):
            if not self._applies(card, context=context):
                continue
            authority = int(getattr(card, "authority_level", 60) or 60)
            multiplier = self._AUTHORITY_MULTIPLIER.get(authority, 0.80)
            results.append(
                KnowledgeCandidate(
                    id=f"knowhow:{card.card_id}",
                    tenant_id=str(context.authz.tenant_id),
                    score=round(0.85 * multiplier, 4),
                    content=(
                        f"[知識卡] {card.title}\n{card.summary or ''}\n"
                        + "\n".join(card.steps or [])
                    ),
                    canonical_resource_type="knowhow_card",
                    canonical_resource_id=str(card.id),
                    result_type="knowhow",
                    title=f"knowhow:{card.title}",
                    provider="knowhow",
                    provider_version=self.provider_version,
                    document_revision=int(card.version or 1),
                    metadata={
                        "type": "knowhow_card",
                        "card_id": card.card_id,
                        "version": card.version,
                        "authority_level": authority,
                        "artifact_type": "knowhow",
                        "source_system": "knowhow",
                        "source_record_id": card.card_id,
                        "source_document_id": card.source_document_id,
                    },
                )
            )
        results.sort(key=lambda row: row.score, reverse=True)
        return results

    def _tenant_module_enabled(self, context: KnowledgeContributionContext) -> bool:
        from sqlalchemy import func, or_

        from app.models.mka import TenantModuleBinding

        return (
            context.db.query(TenantModuleBinding.id)
            .filter(
                TenantModuleBinding.tenant_id == context.authz.tenant_id,
                TenantModuleBinding.module_key == self.module_key,
                TenantModuleBinding.enabled.is_(True),
                TenantModuleBinding.license_state.in_(["trial", "active"]),
                or_(
                    TenantModuleBinding.effective_from.is_(None),
                    TenantModuleBinding.effective_from <= func.now(),
                ),
                or_(
                    TenantModuleBinding.effective_to.is_(None),
                    TenantModuleBinding.effective_to > func.now(),
                ),
            )
            .first()
            is not None
        )
    @staticmethod
    def _applies(card: Any, *, context: KnowledgeContributionContext) -> bool:
        """Fail closed for role/entity-scoped and high-risk field knowledge."""
        query_key = (context.query or "").casefold().replace(" ", "")
        roles = {str(role).casefold() for role in (context.authz.role_ids or [])}
        applicable_roles = {
            str(role).casefold() for role in (card.applicable_roles or [])
        }
        if applicable_roles and not roles.intersection(applicable_roles):
            return False

        for values in (
            card.equipment_ids or [],
            card.product_ids or [],
            card.customer_ids or [],
        ):
            normalized = [
                str(value).casefold().replace(" ", "") for value in values if value
            ]
            if normalized and not any(value in query_key for value in normalized):
                return False

        authority = int(card.authority_level or 0)
        if str(card.risk_level or "").casefold() == "high" and authority < 90:
            return False
        return not (
            any(
                token in query_key
                for token in ("工安", "安全", "危險", "停機", "品質放行")
            )
            and authority < 90
        )
