"""ADR-009 — Gateway 融合不變量（FusionPolicy v1）。

所有進 chat context 與使用者可見 sources 的 hit 必須通過：

1. 可引用性（citation_ok）：無檔名／無穩定 title 的命中不得對使用者可見，
   丟棄必須計數（dropped_non_citable），不得靜默。
2. 權威級（authority_class）：primary_document / compiled_knowledge /
   external_context；禁止跨 class 裸比分截斷當唯一規則。
3. 域隔離（query_domain）：internal_records 域且存在 primary 命中時，
   primary 配額優先，compiled/external 不得排在所有 primary 之前。
4. 觀測：每次融合產出 fusion_policy_version / query_domain /
   dropped_non_citable。

變更本政策必須升 FUSION_POLICY_VERSION 並重跑 FD-FUSION 閘門。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.gateway.contracts import ChunkResult

FUSION_POLICY_VERSION = "1.0"

AUTHORITY_PRIMARY = "primary_document"
AUTHORITY_COMPILED = "compiled_knowledge"
AUTHORITY_EXTERNAL = "external_context"

DOMAIN_INTERNAL_RECORDS = "internal_records"
DOMAIN_GENERAL = "general"

_COMPILED_PROVIDERS = {"weknora", "wiki", "graph", "graphrag"}
_COMPILED_TYPES = {"wiki_page", "graph_entity"}
_EXTERNAL_PROVIDERS = {"pipeshub", "connector"}
_EXTERNAL_TYPES = {"connector_record", "connector"}

# 內部憑證／記錄域提示詞（保守規則；誤傷方向必須是「多留 primary」）
_INTERNAL_RECORDS_HINTS = (
    "憑證", "繳款書", "切結書", "發票", "合約", "契約", "掃描", "表單",
    "入出境", "稅", "簽呈", "單據", "證明", "文件", "檔案", "文件名",
    "工作規則", "手冊", "公告", "流程", "MOU", "mou",
)


def classify_authority(result: ChunkResult) -> str:
    """依 provider／result_type 判定權威級。"""
    provider = (result.provider or "").lower()
    rtype = (result.result_type or "").lower()
    if provider in _COMPILED_PROVIDERS or rtype in _COMPILED_TYPES:
        return AUTHORITY_COMPILED
    if provider in _EXTERNAL_PROVIDERS or rtype in _EXTERNAL_TYPES:
        return AUTHORITY_EXTERNAL
    return AUTHORITY_PRIMARY


def visible_title(result: ChunkResult) -> str:
    meta: Dict[str, Any] = result.metadata or {}
    return str(meta.get("filename") or meta.get("title") or "").strip()


def is_citable(result: ChunkResult) -> bool:
    """可引用性：必須有非空檔名／title；primary 另需可解析 document_id。"""
    if not visible_title(result):
        return False
    if classify_authority(result) == AUTHORITY_PRIMARY:
        return bool(result.document_id)
    return True


def classify_query_domain(query: str) -> str:
    """v1 保守規則分類；演進為分類器時介面不變。"""
    q = query or ""
    if any(h in q for h in _INTERNAL_RECORDS_HINTS):
        return DOMAIN_INTERNAL_RECORDS
    return DOMAIN_GENERAL


@dataclass
class FusionOutcome:
    results: List[ChunkResult] = field(default_factory=list)
    dropped_non_citable: int = 0
    query_domain: str = DOMAIN_GENERAL
    policy_version: str = FUSION_POLICY_VERSION


class FusionPolicy:
    """版本化融合政策；Gateway 與 Chat 出口必須共用同一實作。"""

    version = FUSION_POLICY_VERSION

    def apply(
        self,
        results: List[ChunkResult],
        *,
        query: str,
        top_k: int,
    ) -> FusionOutcome:
        domain = classify_query_domain(query)

        kept: List[ChunkResult] = []
        dropped = 0
        for r in results:
            if is_citable(r):
                kept.append(r)
            else:
                dropped += 1

        if domain == DOMAIN_INTERNAL_RECORDS:
            primaries = [r for r in kept if classify_authority(r) == AUTHORITY_PRIMARY]
            if primaries:
                others = [r for r in kept if classify_authority(r) != AUTHORITY_PRIMARY]
                # primary 配額優先填滿，compiled/external 僅作附錄
                kept = primaries + others
        else:
            # 一般域維持分數序（防禦性排序，不依賴上游已排序）
            kept = sorted(kept, key=lambda r: r.score, reverse=True)

        return FusionOutcome(
            results=kept[:top_k],
            dropped_non_citable=dropped,
            query_domain=domain,
            policy_version=self.version,
        )
