"""VISION Phase 2 — ToolRouter：依 QueryPlan 意圖選檢索／工具臂。"""
from __future__ import annotations

from typing import List

from app.services.query_plan import QueryPlan

# intent → 有序臂列表（chat 主路徑；非 Agent-only）
_INTENT_ARMS = {
    "inventory": ["catalog", "chunk"],
    "multi_hop": ["catalog", "chunk"],
    "compare": ["chunk", "catalog"],
    "translate": ["compiled", "chunk"],
    "fact": ["chunk"],
    "unanswerable": [],  # 仍跑一次 chunk 確認空庫，但不注入 compiled 噪音
}


def arms_for_plan(plan: QueryPlan) -> List[str]:
    """回傳本計劃應執行的臂（保留 plan.arms 若已明示）。"""
    arms = list(plan.arms) if plan.arms else list(_INTENT_ARMS.get(plan.intent, ["chunk"]))
    slots = set(plan.requested_slots or [])
    if slots & {"unit_price", "total_price", "amount", "date", "delivery_date", "quantity", "status", "revision"}:
        arms.insert(0, "structured")
    if slots & {"steps", "procedure", "actor"}:
        arms.insert(0, "procedure")
    return list(dict.fromkeys(arms))


def queries_for_arm(plan: QueryPlan, arm: str, original: str) -> List[str]:
    """每個臂要跑的查詢字串列表。"""
    if arm == "catalog" and plan.sub_queries:
        return list(plan.sub_queries)
    if arm == "chunk" and plan.intent in ("multi_hop", "compare") and plan.sub_queries:
        return list(plan.sub_queries)
    return [original]
