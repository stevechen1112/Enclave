"""Compose domain knowledge providers without coupling the kernel to packs."""

from __future__ import annotations

from app.composition.packs import build_pack_registry
from app.platform.knowledge.providers import KnowledgeProviderRegistry


def build_knowledge_provider_registry() -> KnowledgeProviderRegistry:
    # Deployment capability is resolved by the pack composition root. Tenant
    # entitlement remains request-scoped inside each pack contribution.
    from app.ingestion.video_knowledge_provider import ApprovedVideoProcedureProvider

    return KnowledgeProviderRegistry(
        [
            ApprovedVideoProcedureProvider(),
            *build_pack_registry().knowledge_providers(),
        ]
    )
