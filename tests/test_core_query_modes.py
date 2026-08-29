"""Ask and spec/SOP are core knowledge capabilities, not MKA applications."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.chat import _chat_scopes, _module_retrieval_scope
from app.platform.knowledge import get_query_mode, query_mode_keys
from app.schemas.chat import ChatRequest


def test_spec_sop_is_a_versioned_core_request_contract() -> None:
    request = ChatRequest(question="A-03 的復歸 SOP？", knowledge_mode="spec_sop")
    assert request.knowledge_mode == "spec_sop"
    assert request.module_key is None
    assert query_mode_keys() == ("spec_sop",)


def test_legacy_spec_sop_module_alias_normalizes_to_core_mode() -> None:
    request = SimpleNamespace(module_key="spec_sop", knowledge_mode=None)
    assert _chat_scopes(request) == (None, "spec_sop")


def test_application_module_remains_separate_from_core_mode() -> None:
    request = SimpleNamespace(module_key="quality_8d", knowledge_mode=None)
    assert _chat_scopes(request) == ("quality_8d", None)


def test_core_mode_and_application_module_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        ChatRequest(
            question="建立 8D",
            knowledge_mode="spec_sop",
            module_key="quality_8d",
        )

    compatible = ChatRequest(
        question="查 SOP",
        knowledge_mode="spec_sop",
        module_key="spec_sop",
    )
    assert _chat_scopes(compatible) == (None, "spec_sop")


def test_core_mode_scope_does_not_require_module_registry_or_binding() -> None:
    scope, label = _module_retrieval_scope(
        db=None, authz=None, module_key=None, knowledge_mode="spec_sop"
    )
    assert scope == {"doc_type": ["sop", "spec"], "require_version": True}
    assert label == "規格／SOP 模式"


def test_unknown_query_mode_does_not_add_a_scope() -> None:
    assert get_query_mode("unknown") is None
    scope, label = _module_retrieval_scope(
        db=None, authz=None, module_key=None, knowledge_mode="unknown"
    )
    assert scope == {}
    assert label is None
