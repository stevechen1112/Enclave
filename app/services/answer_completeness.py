"""Final completeness gate used by streaming and non-streaming paths."""
from __future__ import annotations

from typing import Iterable

from app.services.evidence_contract import EvidenceContract, EvidenceItem


def enforce_answer_contract(contract: EvidenceContract, evidence: Iterable[EvidenceItem]) -> dict:
    result = contract.decision(evidence)
    if result["decision"] == "abstain":
        result["message"] = "目前資料不足，尚缺：" + "、".join(result["missing_slots"]) + "。"
    elif result["decision"] == "partial":
        result["message"] = "以下為已有來源支持的部分；尚缺：" + "、".join(result["missing_slots"]) + "。"
    else:
        result["message"] = "所有必要項目均有可驗證來源。"
    return result
