"""Canonical projection shared by retrieval, resolvers and citations."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


UNIT_TYPES = {"document", "chunk", "row", "field", "form", "procedure", "knowhow", "compiled"}


@dataclass(frozen=True)
class KnowledgeUnit:
    tenant_id: str
    document_id: str
    document_revision: str
    unit_id: str
    unit_type: str
    content: str
    content_hash: str
    authority_class: str = "primary_document"
    knowledge_base_id: Optional[str] = None
    kb_revision_id: Optional[str] = None
    acl_snapshot: Dict[str, Any] = field(default_factory=dict)
    policy_revision: int = 1
    entity_ids: List[str] = field(default_factory=list)
    parent_unit_id: Optional[str] = None
    locator: Dict[str, Any] = field(default_factory=dict)
    quality_state: str = "ready"
    versions: Dict[str, str] = field(default_factory=dict)
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    source_refs: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.unit_type not in UNIT_TYPES:
            raise ValueError(f"unsupported unit_type: {self.unit_type}")
        expected = hashlib.sha256(self.content.encode("utf-8", errors="replace")).hexdigest()
        normalized = self.content_hash.removeprefix("sha256:")
        if normalized != expected:
            raise ValueError("content_hash does not match content")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

