"""KQ5 deterministic AnswerPlan, renderer and constrained-paraphrase guard."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from app.services.evidence_orchestrator import EvidenceDecision

ANSWER_PLAN_SCHEMA_VERSION = "1.0"
RENDERER_VERSION = "kq5.1"
ANSWER_TYPES = frozenset(
    {
        "scalar",
        "set",
        "procedure",
        "judgment",
        "definition",
        "comparison",
        "formula",
        "partial_gap",
    }
)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, tuple, set)):
        return "、".join(_display(item) for item in value)
    if isinstance(value, Mapping):
        return "；".join(f"{key}：{_display(item)}" for key, item in value.items())
    return str(value or "").strip()


@dataclass(frozen=True)
class AnswerClaim:
    claim_id: str
    requirement_id: str
    text: str
    value: Any
    value_type: str
    evidence_ids: tuple[str, ...]
    entity_ids: tuple[str, ...] = ()
    locator: dict[str, Any] = field(default_factory=dict)
    document_id: str = ""
    document_revision: str = ""
    knowledge_release_id: str | None = None


@dataclass(frozen=True)
class AnswerPlan:
    decision_id: str
    evidence_state: str
    execution_status: str
    answer_type: str
    direct_conclusion: str
    claims: tuple[AnswerClaim, ...] = ()
    applicability_scope: dict[str, Any] = field(default_factory=dict)
    answered_items: tuple[str, ...] = ()
    missing_items: tuple[dict[str, Any], ...] = ()
    conflicts: tuple[dict[str, Any], ...] = ()
    clarification_question: str | None = None
    source_versions: tuple[dict[str, Any], ...] = ()
    schema_version: str = ANSWER_PLAN_SCHEMA_VERSION
    renderer_version: str = RENDERER_VERSION
    plan_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RenderedAnswer:
    text: str
    claim_ids: tuple[str, ...]
    renderer_version: str
    render_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConstrainedParaphrase:
    text: str
    claim_ids: tuple[str, ...]
    entity_mentions: tuple[str, ...] = ()
    scope_claims: dict[str, Any] = field(default_factory=dict)


def infer_answer_type(query_spec: Mapping[str, Any] | None) -> str:
    spec = dict(query_spec or {})
    explicit = str(spec.get("answer_type") or "").strip().casefold()
    if explicit in ANSWER_TYPES:
        return explicit
    operation = str(spec.get("operation") or "").casefold()
    intent = str(spec.get("intent") or "").casefold()
    shape = str(spec.get("shape") or "").casefold()
    material = " ".join((operation, intent, shape))
    if any(token in material for token in ("yes_no", "judgment", "boolean")):
        return "judgment"
    if any(token in material for token in ("compare", "comparison")):
        return "comparison"
    if any(token in material for token in ("procedure", "workflow", "steps")):
        return "procedure"
    if any(token in material for token in ("aggregate", "formula", "calculate")):
        return "formula"
    if any(token in material for token in ("list", "set", "inventory")):
        return "set"
    if "definition" in material:
        return "definition"
    return "scalar"


def build_answer_plan(
    decision: EvidenceDecision,
    *,
    query_spec: Mapping[str, Any] | None = None,
) -> AnswerPlan:
    """Compile a content-addressed presentation plan from verified claims only."""
    answer_type = infer_answer_type(query_spec)
    claims: list[AnswerClaim] = []
    sources: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for item in decision.verified_claims:
        evidence_id = str(item.evidence_id or item.unit_id)
        claim_id = "claim:" + _digest(
            {
                "decision_id": decision.decision_id,
                "evidence_id": evidence_id,
                "requirement_id": item.slot_id,
                "value": item.value,
            }
        )[:24]
        claim = AnswerClaim(
            claim_id=claim_id,
            requirement_id=item.slot_id,
            text=_display(item.value),
            value=item.value,
            value_type=item.value_type,
            evidence_ids=(evidence_id,),
            entity_ids=(str(item.entity_id),) if item.entity_id else (),
            locator=dict(item.locator or {}),
            document_id=str(item.document_id or ""),
            document_revision=str(item.document_revision or ""),
            knowledge_release_id=item.knowledge_release_id,
        )
        claims.append(claim)
        key = (
            claim.document_id,
            claim.document_revision,
            claim.knowledge_release_id,
        )
        sources[key] = {
            "document_id": claim.document_id,
            "document_revision": claim.document_revision,
            "knowledge_release_id": claim.knowledge_release_id,
            "locator": claim.locator,
        }

    state = decision.evidence_state
    final_answer_type = "partial_gap" if state == "partial" else answer_type
    if decision.execution_status != "ok":
        conclusion = "系統未完成本次判斷。"
    elif state == "conflict":
        conclusion = "來源存在尚未能消解的差異。"
    elif state == "absent":
        conclusion = "指定範圍內未找到可驗證依據。"
    elif state == "insufficient_context":
        conclusion = "還需要一項必要資訊才能判斷。"
    elif claims:
        conclusion = _display(claims[0].value)
        if answer_type == "judgment":
            conclusion = f"{conclusion.rstrip('。')}。"
        elif state == "partial":
            conclusion = f"目前可確認：{conclusion}"
    else:
        conclusion = "目前沒有可安全輸出的已驗證結論。"

    missing = tuple(dict(item) for item in decision.missing_requirements)
    clarification = None
    if state == "insufficient_context" and missing:
        label = str(missing[0].get("label") or missing[0].get("requirement_id"))
        clarification = f"請補充「{label}」。"
    conflicts = tuple(asdict(item) for item in decision.conflicts)
    stable = {
        "decision_id": decision.decision_id,
        "evidence_state": state,
        "execution_status": decision.execution_status,
        "answer_type": final_answer_type,
        "direct_conclusion": conclusion,
        "claims": [asdict(item) for item in claims],
        "applicability_scope": decision.reviewed_scope,
        "answered_items": decision.answered_requirements,
        "missing_items": missing,
        "conflicts": conflicts,
        "clarification_question": clarification,
        "source_versions": list(sources.values()),
        "schema_version": ANSWER_PLAN_SCHEMA_VERSION,
        "renderer_version": RENDERER_VERSION,
    }
    return AnswerPlan(
        decision_id=decision.decision_id,
        evidence_state=state,
        execution_status=decision.execution_status,
        answer_type=final_answer_type,
        direct_conclusion=conclusion,
        claims=tuple(claims),
        applicability_scope=dict(decision.reviewed_scope),
        answered_items=tuple(decision.answered_requirements),
        missing_items=missing,
        conflicts=conflicts,
        clarification_question=clarification,
        source_versions=tuple(sources.values()),
        plan_hash=_digest(stable),
    )


def _render_claims(claims: Iterable[AnswerClaim], *, numbered: bool) -> list[str]:
    rows = []
    for index, claim in enumerate(claims, 1):
        marker = f"{index}." if numbered else "-"
        rows.append(f"{marker} {claim.text}")
    return rows


def render_answer_plan(plan: AnswerPlan) -> RenderedAnswer:
    """Render without a model; no text can escape the verified plan."""
    lines = [plan.direct_conclusion]
    used_claims: list[AnswerClaim] = []
    if plan.execution_status != "ok":
        lines.extend(("", "請稍後重試；若持續發生，請使用追蹤碼聯絡管理員。"))
    elif plan.evidence_state == "conflict":
        lines.extend(("", "請查看來源版本與適用範圍，交由負責人確認。"))
    elif plan.evidence_state == "insufficient_context":
        if plan.clarification_question:
            lines.extend(("", plan.clarification_question))
    elif plan.evidence_state == "absent":
        lines.extend(("", "可擴大查詢範圍，或新增／發布相關知識後再試。"))
    else:
        used_claims = list(plan.claims)
        if plan.answer_type in {"set", "partial_gap"} and plan.claims:
            lines.extend(("", "已確認項目：", *_render_claims(plan.claims, numbered=False)))
        elif plan.answer_type == "procedure" and plan.claims:
            lines.extend(("", "執行順序：", *_render_claims(plan.claims, numbered=True)))
        elif plan.answer_type == "comparison" and plan.claims:
            lines.extend(("", "比較結果：", *_render_claims(plan.claims, numbered=False)))
        elif plan.answer_type == "formula" and plan.claims:
            lines.extend(("", "計算依據：", *_render_claims(plan.claims, numbered=False)))
        elif len(plan.claims) > 1:
            lines.extend(("", "條件與依據：", *_render_claims(plan.claims[1:], numbered=False)))
        if plan.missing_items:
            labels = [
                str(item.get("label") or item.get("requirement_id") or "必要項目")
                for item in plan.missing_items
            ]
            lines.extend(("", "尚缺項目：" + "、".join(labels)))
        scope = {
            key: value
            for key, value in plan.applicability_scope.items()
            if value not in (None, "", [], (), {})
        }
        if scope:
            lines.extend(("", "適用範圍：" + _display(scope)))
        if plan.source_versions:
            versions = [
                f"{item.get('document_id') or '來源'}@{item.get('document_revision') or '未標示'}"
                for item in plan.source_versions
            ]
            lines.extend(("", "來源版本：" + "、".join(versions)))
    text = "\n".join(lines).strip()
    claim_ids = tuple(claim.claim_id for claim in used_claims)
    return RenderedAnswer(
        text=text,
        claim_ids=claim_ids,
        renderer_version=plan.renderer_version,
        render_hash=_digest(
            {
                "plan_hash": plan.plan_hash,
                "text": text,
                "claim_ids": claim_ids,
                "renderer_version": plan.renderer_version,
            }
        ),
    )


def render_constrained_or_fallback(
    plan: AnswerPlan,
    draft: ConstrainedParaphrase | None,
) -> RenderedAnswer:
    """Accept a declared-claim paraphrase or deterministically fall back."""
    if draft is None:
        return render_answer_plan(plan)
    from app.services.source_verifier import validate_answer_plan_claims

    result = validate_answer_plan_claims(
        plan,
        answer=draft.text,
        claim_ids=draft.claim_ids,
        entity_mentions=draft.entity_mentions,
        scope_claims=draft.scope_claims,
    )
    if not result["verified"]:
        return render_answer_plan(plan)
    return RenderedAnswer(
        text=draft.text.strip(),
        claim_ids=tuple(draft.claim_ids),
        renderer_version=plan.renderer_version,
        render_hash=_digest(
            {
                "plan_hash": plan.plan_hash,
                "text": draft.text.strip(),
                "claim_ids": draft.claim_ids,
                "renderer_version": plan.renderer_version,
            }
        ),
    )
