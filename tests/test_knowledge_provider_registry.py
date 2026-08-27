from __future__ import annotations

import pytest

from app.core.authorization import AuthorizationContext
from app.platform.knowledge import KnowledgeCandidate, KnowledgeProviderRegistry


class _Provider:
    provider_key = "test.provider"
    provider_version = "1.0"
    capability_keys = ("test.read",)

    def contribute(self, context):
        return [
            KnowledgeCandidate(
                id="u-1",
                tenant_id=str(context.authz.tenant_id),
                content=context.query,
                score=0.8,
                canonical_resource_type="test_unit",
                canonical_resource_id="unit-1",
                result_type="test_unit",
                title="Test unit",
                provider="test",
                provider_version=self.provider_version,
            )
        ]


class _FailedProvider:
    provider_key = "test.failed"
    provider_version = "1.0"
    capability_keys = ("test.read",)

    def contribute(self, context):
        raise RuntimeError("unavailable")


class _MalformedProvider:
    provider_key = "test.malformed"
    provider_version = "1.0"
    capability_keys = ("test.read",)

    def contribute(self, context):
        return [42]


def _authz():
    from uuid import UUID

    return AuthorizationContext(
        tenant_id=UUID(int=1),
        subject_id=UUID(int=2),
        role_ids=["employee"],
    )


def _contribute(registry, **kwargs):
    return registry.contribute(
        authz=_authz(), query="hello", db=None, top_k=10, **kwargs
    )


def test_registry_tags_typed_contributions_with_provider_key():
    batch = _contribute(KnowledgeProviderRegistry([_Provider()]))
    rows = batch.to_retrieval_dicts()

    assert rows[0]["content"] == "hello"
    assert rows[0]["metadata"]["knowledge_provider_key"] == "test.provider"
    assert rows[0]["metadata"]["canonical_resource_id"] == "unit-1"
    assert not batch.degraded


def test_registry_provider_failure_is_fail_closed_and_observable():
    batch = _contribute(KnowledgeProviderRegistry([_FailedProvider(), _Provider()]))

    assert [row["id"] for row in batch.to_retrieval_dicts()] == ["u-1"]
    assert batch.degraded
    assert batch.failures[0].code == "provider_unavailable"


def test_registry_malformed_output_does_not_crash_retrieval():
    batch = _contribute(KnowledgeProviderRegistry([_MalformedProvider(), _Provider()]))

    assert [row["id"] for row in batch.to_retrieval_dicts()] == ["u-1"]
    assert batch.failures[0].code == "invalid_output"


def test_registry_rejects_duplicate_keys():
    registry = KnowledgeProviderRegistry([_Provider()])
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(_Provider())


def test_registry_requires_version_and_capabilities():
    class Incomplete:
        provider_key = "incomplete"

        def contribute(self, context):
            return []

    with pytest.raises(ValueError, match="provider_version"):
        KnowledgeProviderRegistry([Incomplete()])


def test_context_exposes_scope_and_limits_provider_rows():
    seen = {}

    class Many(_Provider):
        provider_key = "test.many"

        def contribute(self, context):
            seen["scope"] = dict(context.scope)
            seen["top_k"] = context.top_k
            return [
                KnowledgeCandidate(
                    id=f"u-{i}",
                    tenant_id=str(context.authz.tenant_id),
                    content="x",
                    score=0.5,
                    canonical_resource_type="test",
                    canonical_resource_id=f"r-{i}",
                    result_type="test",
                    title="test",
                    provider="test",
                    provider_version=self.provider_version,
                )
                for i in range(5)
            ]

    batch = KnowledgeProviderRegistry([Many()]).contribute(
        authz=_authz(),
        query="x",
        db=None,
        top_k=2,
        scope={"kb_revision_ids": ["r1"]},
    )
    assert len(batch.candidates) == 2
    assert seen == {"scope": {"kb_revision_ids": ["r1"]}, "top_k": 2}


def test_retrieval_surfaces_provider_failure_as_partial(monkeypatch):
    from app.services.kb_retrieval import KnowledgeBaseRetriever
    from app.services.retrieval_facade import RetrievalFacade

    monkeypatch.setattr(KnowledgeBaseRetriever, "search", lambda *args, **kwargs: [])
    result = RetrievalFacade(
        providers=KnowledgeProviderRegistry([_FailedProvider()])
    ).search(authz=_authz(), query="x", top_k=1)

    assert result.results == []
    assert result.gateway_status == "partial"
    assert result.provider_failures[0].provider_key == "test.failed"
