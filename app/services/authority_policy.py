"""Contextual source authority, conflict and expiry policy."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class AuthorityEvidence:
    evidence_id: str
    authority_class: str
    value: str
    source_ref: Dict[str, object]
    approved: bool = True
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    scope: Dict[str, str] = field(default_factory=dict)


class AuthorityPolicy:
    DEFAULT = ["system_record", "primary_document", "approved_knowhow", "external_regulation", "compiled_knowledge"]

    def rank(self, evidence: Iterable[AuthorityEvidence], *, context: Dict[str, str], risk_class: str = "normal", at: Optional[datetime] = None) -> dict:
        now = at or datetime.now(timezone.utc)
        usable: List[AuthorityEvidence] = []
        excluded: List[dict] = []
        for item in evidence:
            reason = None
            if not item.approved:
                reason = "not_approved"
            elif item.effective_from and item.effective_from > now:
                reason = "not_yet_effective"
            elif item.effective_to and item.effective_to <= now:
                reason = "expired"
            elif any(str(context.get(k, "")) != str(v) for k, v in item.scope.items()):
                reason = "scope_mismatch"
            elif risk_class == "safety_critical" and item.authority_class not in {"primary_document", "system_record"}:
                reason = "insufficient_safety_authority"
            if reason:
                excluded.append({"evidence_id": item.evidence_id, "reason": reason})
            else:
                usable.append(item)
        order = {name: i for i, name in enumerate(self.DEFAULT)}
        usable.sort(key=lambda e: order.get(e.authority_class, len(order)))
        values = {e.value for e in usable}
        return {"usable": usable, "excluded": excluded, "conflict": len(values) > 1,
                "decision": "abstain" if not usable else ("conflict" if len(values) > 1 else "answer")}

