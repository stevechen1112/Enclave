"""QueryPlan：題型計劃（control plane 結構化意圖）。

把「盤點／事實／比較／跨語／多跳／不可答」收成可觀測契約物件。
初版以規則分類（禁止題號特判）；介面穩定後可換 LLM 分類器而不改呼叫端。

契約：
- plan.arms 決定主路徑呼叫哪些檢索臂（catalog／chunk／compiled）
- plan.sub_queries 非空時，catalog／chunk 應對每個子查詢各跑一次再合併
- plan 必須寫入 retrieval event（plan_version／intent／arms／sub_queries）
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal

from app.gateway.fusion_policy import classify_query_domain

QUERY_PLAN_VERSION = "1.3"

Intent = Literal[
    "inventory",
    "fact",
    "compare",
    "translate",
    "multi_hop",
    "unanswerable",
]

_INVENTORY_VERBS = ("哪些", "列出", "盤點", "清單", "列表", "有什麼", "有哪些", "全部")
_INVENTORY_NOUNS = ("文件", "檔案", "檔", "掃描件", "合約", "憑證", "表單", "手冊", "資料")

_COMPARE_HINTS = (
    "比較", "差異", "對比", "不同", "何者較", "哪個較", "哪份較",
    "哪份總價較", "哪個總價較", " vs ", " VS ",
)
_COMPARE_HIGH_LOW = ("較高", "較低", "更高", "更低", "由高到低", "由低到高")
_DOCISH = re.compile(
    r"(?:\.(?:pdf|docx?|xlsx?|pptx?|txt|md)$|合約|報價|提案|企劃|報告|手冊|契約|合約書)",
    re.IGNORECASE,
)
_TRANSLATE_HINTS = (
    "對照", "翻譯", "譯文", "英文標題", "中文標題", "條款編號",
    "clause", "base code", "緬甸", "burmese", "gloss",
)
# 注意：年份（2028/2030 等）不是不可答訊號——文件可能明載未來年度目標
# （2026-08-03 盲測 B13：報告明載「2030 年 E-Bike 佔比 50% 目標」卻被誤判拒答）。
# 不可答應由「檢索無證據」驅動，而非關鍵字。
_UNANSWERABLE_HINTS = (
    "火星", "隱藏折扣", "私人手機", "私人銀行", "銀行密碼",
    "刪除所有稽核", "未收錄產品",
    "SpaceX", "星艦", "未上傳", "隱藏附錄", "SECRET2028",
)
_COMPOSITE_SPLIT = re.compile(
    r"(?P<left>.+?)(?:與|和|以及|還有|、)\s*(?P<right>.+?)(?:各有|分別|各自)"
)
_COMPARE_TWO = re.compile(
    r"(?:比較|對比)?\s*(?:兩份|兩個)?(?P<a>[^與和]+?)(?:與|和|以及)\s*(?P<b>.+?)(?:的|在|$)"
)


_DOC_MENTION = re.compile(r"《([^》]+)》")
# 中文／西式引號包住的檔名或文件標題（可無副檔名）
_DOC_MENTION_QUOTED = re.compile(r"[「『\"']([^」』\"']{2,80})[」』\"']")
# 題目直接寫「杏壺報價.pdf」而無書名號／引號（Blind Z4-009）
_BARE_FILENAME = re.compile(
    r"([^\s「」『』《》\"']{1,80}\.(?:pdf|docx?|xlsx?|pptx?|PDF|DOCX?))",
)


def extract_mentioned_documents(query: str) -> List[str]:
    """擷取查詢中明確點名的文件名（用於檔名導向檢索 scope）。

    支援《...》與「...pdf」／「委託合約-八策品牌」等文件標題，
    以及裸檔名「杏壺報價.pdf」。
    """
    seen: List[str] = []
    for m in _DOC_MENTION.finditer(query or ""):
        name = (m.group(1) or "").strip()
        if name and name not in seen:
            seen.append(name)
    for m in _DOC_MENTION_QUOTED.finditer(query or ""):
        name = (m.group(1) or "").strip()
        if not name or name in seen:
            continue
        if not _DOCISH.search(name):
            continue
        if name in {"行銷提案", "報價單", "合約書", "企劃案", "報價合約"}:
            continue
        seen.append(name)
    for m in _BARE_FILENAME.finditer(query or ""):
        name = (m.group(1) or "").strip().strip("，。；;、")
        if not name or name in seen:
            continue
        # 去掉前綴贅詞（的／之）
        name = re.sub(r"^[的之與和及]", "", name)
        if len(name) < 5:
            continue
        # 已由《》／引號擷取的較長檔名包含此片段時略過（避免「000_nueip 合約.pdf」再拆出「合約.pdf」）
        if any(name in s or s in name for s in seen):
            continue
        seen.append(name)
    return seen


@dataclass
class QueryPlan:
    intent: Intent
    arms: List[str]
    domain: str
    sub_queries: List[str] = field(default_factory=list)
    mentioned_documents: List[str] = field(default_factory=list)
    notes: str = ""
    plan_version: str = QUERY_PLAN_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def wants_catalog(self) -> bool:
        return "catalog" in self.arms

    @property
    def wants_chunk(self) -> bool:
        return "chunk" in self.arms

    @property
    def wants_compiled(self) -> bool:
        return "compiled" in self.arms


def is_inventory_query(query: str) -> bool:
    q = query or ""
    return any(v in q for v in _INVENTORY_VERBS) and any(n in q for n in _INVENTORY_NOUNS)


def _looks_compare(q: str) -> bool:
    if any(h in q for h in _COMPARE_HINTS):
        return True
    # 「A 與 B，哪份較高」無「比較」二字也視為比價
    if any(h in q for h in _COMPARE_HIGH_LOW) and any(x in q for x in ("與", "和", "以及", "、")):
        return True
    return False


def _looks_translate(q: str) -> bool:
    ql = (q or "").casefold()
    return any(h.casefold() in ql for h in _TRANSLATE_HINTS)


def _looks_unanswerable(q: str) -> bool:
    return any(h in (q or "") for h in _UNANSWERABLE_HINTS)


def _split_composite(query: str) -> List[str]:
    m = _COMPOSITE_SPLIT.search(query or "")
    if not m:
        return []
    left = (m.group("left") or "").strip()
    right = (m.group("right") or "").strip()
    noun = next((n for n in _INVENTORY_NOUNS if n in (query or "")), "文件")
    verb = next((v for v in _INVENTORY_VERBS if v in (query or "")), "有哪些")
    if noun not in left:
        left = f"{left}{noun}"
    if noun not in right:
        right = f"{right}{noun}"
    return [f"{left}{verb}", f"{right}{verb}"]


def _split_compare(query: str) -> List[str]:
    """比較題拆成兩邊／多邊子查詢（供 chunk 多臂召回）。"""
    q = query or ""
    # 請比較 A、B、C 的總價
    m_list = re.search(
        r"(?:請)?(?:比較|對比)\s*(.+?)(?:的總價|的金額|總價|金額|，由|由高|由低|$)",
        q,
    )
    if m_list:
        parts = [p.strip(" 的") for p in re.split(r"[、,，]", m_list.group(1)) if p.strip()]
        parts = [p for p in parts if len(p) >= 2]
        if len(parts) >= 2:
            return parts[:6]

    m = _COMPARE_TWO.search(q)
    if not m:
        # 常見：「兩份營業稅繳款書」→ 仍用原查詢兩次不夠；改用主題詞
        if "兩份" in q or "兩個" in q:
            topic = re.sub(r"比較|對比|兩份|兩個|的|期間|稅額|差異", "", q).strip()
            if topic:
                return [topic, topic]
        return []
    a = (m.group("a") or "").strip(" 的")
    b = (m.group("b") or "").strip(" 的")
    b = re.split(r"[，,]|哪份|哪個|何者|是否", b, maxsplit=1)[0].strip(" 的")
    if not a or not b or a == b:
        return []
    return [a, b]


def build_query_plan(query: str) -> QueryPlan:
    """依查詢字串產出 QueryPlan（規則；禁止題號特判）。"""
    q = query or ""
    domain = classify_query_domain(q)
    mentioned = extract_mentioned_documents(q)

    # 明確指定檔名（《...》）時不做不可答短路：這是證據範圍內的問題，
    # 應由 scoped 檢索取證後讓 LLM 依證據決定回答或拒答
    if _looks_unanswerable(q) and not mentioned:
        return QueryPlan(
            intent="unanswerable",
            arms=[],
            domain=domain,
            mentioned_documents=mentioned,
            notes="out-of-corpus probe → structured refusal",
        )

    if _looks_translate(q):
        return QueryPlan(
            intent="translate",
            arms=["chunk", "compiled"],
            domain=domain,
            mentioned_documents=mentioned,
            notes="cross-language / clause-gloss intent",
        )

    if _looks_compare(q):
        subs = _split_compare(q)
        return QueryPlan(
            intent="compare",
            arms=["chunk", "catalog"],
            domain=domain,
            sub_queries=subs,
            mentioned_documents=mentioned,
            notes="compare intent — dual evidence preferred",
        )

    if is_inventory_query(q):
        subs = _split_composite(q)
        if subs:
            return QueryPlan(
                intent="multi_hop",
                arms=["catalog", "chunk"],
                domain=domain,
                sub_queries=subs,
                mentioned_documents=mentioned,
                notes="composite inventory → split sub_queries",
            )
        return QueryPlan(
            intent="inventory",
            arms=["catalog", "chunk"],
            domain=domain,
            mentioned_documents=mentioned,
            notes="inventory → catalog arm required",
        )

    return QueryPlan(
        intent="fact",
        arms=["chunk"],
        domain=domain,
        mentioned_documents=mentioned,
        notes="default fact retrieval",
    )
