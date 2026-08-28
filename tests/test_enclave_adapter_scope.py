from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.core.authorization import AuthorizationContext
from app.gateway.adapters.enclave import EnclaveCanonicalAdapter


@pytest.mark.asyncio
async def test_enclave_adapter_applies_revision_scope_before_ranking():
    scope = {"kb_revision_ids": [str(uuid4())]}
    retriever = MagicMock()
    retriever.search.return_value = [
        {
            "id": "chunk-1",
            "content": "published evidence",
            "score": 0.9,
            "document_id": str(uuid4()),
            "document_revision": 7,
            "filename": "published.md",
            "chunk_index": 2,
        }
    ]
    adapter = EnclaveCanonicalAdapter()
    adapter._retriever = retriever
    authz = AuthorizationContext(
        tenant_id=uuid4(),
        subject_id=uuid4(),
        role_ids=["employee"],
    )

    results = await adapter.search(authz, "published", top_k=3, scope=scope)

    assert retriever.search.call_args.kwargs["filter_dict"] == scope
    assert results[0].document_revision == 7
    assert results[0].metadata["document_revision"] == 7
