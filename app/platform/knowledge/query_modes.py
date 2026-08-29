"""Core Ask query modes; these are not optional application modules."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class KnowledgeQueryMode:
    key: str
    label: str
    retrieval_scope: Mapping[str, Any]


_QUERY_MODES = {
    "spec_sop": KnowledgeQueryMode(
        key="spec_sop",
        label="規格／SOP 模式",
        retrieval_scope=MappingProxyType(
            {"doc_type": ["sop", "spec"], "require_version": True}
        ),
    )
}
_LEGACY_ASK_TASK_KEYS = frozenset({"ask"})


def get_query_mode(key: str | None) -> KnowledgeQueryMode | None:
    if not key:
        return None
    return _QUERY_MODES.get(str(key).strip())


def is_core_query_mode(key: str | None) -> bool:
    return get_query_mode(key) is not None


def query_mode_keys() -> tuple[str, ...]:
    return tuple(_QUERY_MODES)


def is_legacy_ask_task(key: str | None) -> bool:
    return bool(key) and str(key).strip() in _LEGACY_ASK_TASK_KEYS
