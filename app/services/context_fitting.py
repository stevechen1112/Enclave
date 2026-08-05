"""
P0-1：Context Fitting — 依 token 預算裁切 context，避免 parent/sibling 擴展後超窗。

借鑑 OpenDocuments 的 context-window.ts：依 token budget 保留高價值內容，
避免 parent／sibling 擴展後超窗。citation 仍指向原 chunk，不丟失溯源。

設計原則：
- DB 應保存 raw chunk；parent/sibling 只是生成上下文
- citation 仍需指向原 chunk（不替換 citation 來源）
- parent section 不可把多文件來源混成一段
- 去重：相同 document_id + chunk_index 不重複加入
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── Token 估算 ──
# 粗估：中文 ~1.5 token/字，英文 ~0.25 token/字（4 字/token）
# 不引入 tiktoken 以避免額外依賴；精確度足夠做預算控制


def estimate_tokens(text: str) -> int:
    """粗估文字的 token 數。"""
    if not text:
        return 0
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
    ascii_count = len(text) - cjk_count
    # CJK ~1.5 token/字，ASCII ~0.25 token/字
    return int(cjk_count * 1.5 + ascii_count * 0.25) + 1


@dataclass
class FittedContext:
    """Context fitting 結果。"""
    parts: List[str] = field(default_factory=list)
    included_chunks: List[Dict[str, Any]] = field(default_factory=list)
    dropped_chunks: List[Dict[str, Any]] = field(default_factory=list)
    total_tokens: int = 0
    budget: int = 0
    deduplicated: int = 0

    @property
    def truncated(self) -> bool:
        return bool(self.dropped_chunks)


def fit_context(
    chunks: List[Dict[str, Any]],
    token_budget: int = 6000,
    citation_format: str = "[來源 {idx}] (doc:{doc})\n{text}",
    deduplicate: bool = True,
) -> FittedContext:
    """依 token 預算裁切 context。

    Args:
        chunks: 已排序的 chunk dict 列表（score 高→低），每個含 content/text, document_id, chunk_index 等
        token_budget: 總 token 預算（不含 citation 標記的額外 token）
        citation_format: 每個 chunk 的格式化模板，可用 {idx}, {doc}, {text}
        deduplicate: 是否依 (document_id, chunk_index) 去重

    Returns:
        FittedContext: 包含 parts（格式化字串）、included/dropped chunks、token 統計
    """
    result = FittedContext(budget=token_budget)
    seen: Set[Tuple[str, int]] = set()
    current_tokens = 0

    # citation 標記的額外 token 估算（約 10 token/chunk）
    citation_overhead = 10

    for chunk_idx, chunk in enumerate(chunks):
        text = chunk.get("text") or chunk.get("content") or ""
        doc_id = str(chunk.get("document_id") or "")[:8]
        chunk_index = chunk.get("chunk_index", -1)

        # 去重
        if deduplicate:
            key = (str(chunk.get("document_id") or ""), int(chunk_index))
            if key in seen:
                result.deduplicated += 1
                continue
            seen.add(key)

        chunk_tokens = estimate_tokens(text) + citation_overhead

        # 預算檢查
        if current_tokens + chunk_tokens > token_budget:
            # 嘗試截斷最後一個 chunk 以填滿預算
            remaining = token_budget - current_tokens
            if remaining > 50:  # 至少剩 50 token 才值得截斷
                truncated_text = _truncate_to_tokens(text, remaining - citation_overhead)
                if truncated_text:
                    idx = len(result.included_chunks) + 1
                    result.parts.append(citation_format.format(idx=idx, doc=doc_id, text=truncated_text))
                    result.included_chunks.append({**chunk, "_truncated": True})
                    current_tokens += estimate_tokens(truncated_text) + citation_overhead

            result.dropped_chunks.append(chunk)
            # 預算用盡，後續全部 dropped（用 enumerate 索引，避免 O(n²) 的 list.index）
            for remaining_chunk in chunks[chunk_idx + 1:]:
                if deduplicate:
                    rkey = (str(remaining_chunk.get("document_id") or ""), int(remaining_chunk.get("chunk_index", -1)))
                    if rkey in seen:
                        continue
                    seen.add(rkey)
                result.dropped_chunks.append(remaining_chunk)
            break

        idx = len(result.included_chunks) + 1
        result.parts.append(citation_format.format(idx=idx, doc=doc_id, text=text))
        result.included_chunks.append(chunk)
        current_tokens += chunk_tokens

    result.total_tokens = current_tokens
    return result


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """截斷文字到約 max_tokens 的長度。"""
    if max_tokens <= 0:
        return ""
    # 粗估：每 token 約 0.7 字（混合 CJK/ASCII）
    max_chars = int(max_tokens / 0.7)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…（截斷）"


def merge_parent_and_chunks(
    original_chunks: List[Dict[str, Any]],
    parent_map: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """將 parent document 文本合併進 chunk 列表。

    Args:
        original_chunks: 原始命中 chunk 列表（已排序）
        parent_map: chunk_id → parent chunk dict（含 text, document_id, chunk_index 等）

    Returns:
        合併後的 chunk 列表，parent 文本附加在對應 chunk 之前，citation 仍指向原 chunk
    """
    merged: List[Dict[str, Any]] = []
    seen_parents: Set[str] = set()

    # 在迴圈外讀取一次，避免每次迴圈都 import + 讀 settings
    parent_enabled = PARENT_DOC_ENABLED_CHECK()
    if not parent_enabled:
        return list(original_chunks)

    for chunk in original_chunks:
        chunk_id = str(chunk.get("id") or "")
        parent = parent_map.get(chunk_id)

        if parent:
            parent_id = str(parent.get("id") or "")
            parent_doc_id = str(parent.get("document_id") or "")
            # parent 必須與 chunk 同文件（不混文件）
            if (
                parent_id
                and parent_id not in seen_parents
                and parent_doc_id == str(chunk.get("document_id") or "")
            ):
                seen_parents.add(parent_id)
                # parent 作為上下文前置，但 citation 仍指向原 chunk
                merged.append({
                    **parent,
                    "_is_parent": True,
                    "_citation_chunk_id": chunk_id,  # citation 指向原 chunk
                    "score": chunk.get("score", 0) * 0.95,  # parent 略降
                })

        merged.append(chunk)

    return merged


def expand_siblings(
    chunks: List[Dict[str, Any]],
    sibling_lookup: Dict[str, List[Dict[str, Any]]],
    window: int = 1,
    score_discount: float = 0.85,
) -> List[Dict[str, Any]]:
    """附加相鄰 sibling chunk。

    Args:
        chunks: 原始命中 chunk 列表
        sibling_lookup: chunk_id → [sibling chunk dicts]（同文件、相鄰 chunk_index）
        window: 每側擴展幾個 sibling
        score_discount: sibling 的 score 乘以此折扣

    Returns:
        擴展後的 chunk 列表，sibling 附加在對應 chunk 之後
    """
    expanded: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, int]] = set()

    for chunk in chunks:
        chunk_id = str(chunk.get("id") or "")
        doc_id = str(chunk.get("document_id") or "")
        chunk_index = int(chunk.get("chunk_index", -1))

        # 原始 chunk
        key = (doc_id, chunk_index)
        if key not in seen:
            seen.add(key)
            expanded.append(chunk)

        # siblings — 按 chunk_index 排序後取前後各 window 個
        siblings = sibling_lookup.get(chunk_id, [])
        # 按 chunk_index 排序，確保取的是真正相鄰的 sibling
        sorted_siblings = sorted(siblings, key=lambda s: int(s.get("chunk_index", -1)))
        # 分前後各 window 個
        prev_sibs = [s for s in sorted_siblings if int(s.get("chunk_index", -1)) < chunk_index][-window:]
        next_sibs = [s for s in sorted_siblings if int(s.get("chunk_index", -1)) > chunk_index][:window]
        selected_siblings = prev_sibs + next_sibs
        for sibling in selected_siblings:
            sib_index = int(sibling.get("chunk_index", -1))
            sib_key = (str(sibling.get("document_id") or ""), sib_index)
            if sib_key in seen:
                continue
            seen.add(sib_key)
            expanded.append({
                **sibling,
                "_is_sibling": True,
                "_citation_chunk_id": chunk_id,  # citation 指向原始命中 chunk
                "score": chunk.get("score", 0) * score_discount,
            })

    return expanded


def PARENT_DOC_ENABLED_CHECK() -> bool:
    """延遲讀取 settings 以避免循環匯入。"""
    from app.config import settings
    return settings.PARENT_DOC_ENABLED