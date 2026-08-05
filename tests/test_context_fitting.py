"""
P0-1：Parent Document + Sibling Expansion + Context Fitting 單元測試。

驗收標準（對照稽核文件 §4.4）：
- Parent section 單元測試：擴展、去重、citation 不丟失
- 跨 chunk 題 Hit@5／answer correctness 提升（需 ablation，此處只測單元邏輯）
- p95 latency 與 token 使用量（需 ablation）
"""
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4, UUID

from app.services.context_fitting import (
    estimate_tokens,
    fit_context,
    merge_parent_and_chunks,
    expand_siblings,
    FittedContext,
)


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_cjk(self):
        # 純中文：~1.5 token/字
        tokens = estimate_tokens("這是一段中文文字")
        assert tokens > 0
        # 8 字 * 1.5 = 12 + 1 = 13
        assert tokens == 13

    def test_ascii(self):
        # 純英文：~0.25 token/字
        tokens = estimate_tokens("hello world")
        assert tokens > 0
        # 11 字 * 0.25 = 2.75 → 2 + 1 = 3
        assert tokens == 3

    def test_mixed(self):
        tokens = estimate_tokens("這是 hello 世界 world")
        assert tokens > 0


class TestFitContext:
    def test_basic_fit(self):
        chunks = [
            {"content": "chunk 1", "document_id": "doc1", "chunk_index": 0, "score": 0.9},
            {"content": "chunk 2", "document_id": "doc2", "chunk_index": 0, "score": 0.8},
        ]
        result = fit_context(chunks, token_budget=1000)
        assert len(result.parts) == 2
        assert len(result.included_chunks) == 2
        assert len(result.dropped_chunks) == 0
        assert not result.truncated

    def test_budget_truncation(self):
        # 大 chunk 超過預算
        big_text = "A" * 10000
        chunks = [
            {"content": big_text, "document_id": "doc1", "chunk_index": 0, "score": 0.9},
            {"content": "small", "document_id": "doc2", "chunk_index": 0, "score": 0.8},
        ]
        result = fit_context(chunks, token_budget=100)
        # 第一個 chunk 會被截斷，第二個會 dropped
        assert result.truncated
        assert len(result.dropped_chunks) >= 1

    def test_deduplication(self):
        chunks = [
            {"content": "chunk 1", "document_id": "doc1", "chunk_index": 0, "score": 0.9},
            {"content": "chunk 1 dup", "document_id": "doc1", "chunk_index": 0, "score": 0.85},
            {"content": "chunk 2", "document_id": "doc1", "chunk_index": 1, "score": 0.8},
        ]
        result = fit_context(chunks, token_budget=10000, deduplicate=True)
        assert result.deduplicated == 1
        assert len(result.included_chunks) == 2

    def test_no_dedup(self):
        chunks = [
            {"content": "chunk 1", "document_id": "doc1", "chunk_index": 0, "score": 0.9},
            {"content": "chunk 1 dup", "document_id": "doc1", "chunk_index": 0, "score": 0.85},
        ]
        result = fit_context(chunks, token_budget=10000, deduplicate=False)
        assert result.deduplicated == 0
        assert len(result.included_chunks) == 2

    def test_citation_format(self):
        chunks = [
            {"content": "hello", "document_id": "abc12345", "chunk_index": 0, "score": 0.9},
        ]
        result = fit_context(chunks, token_budget=1000)
        assert "[來源 1]" in result.parts[0]
        assert "abc1" in result.parts[0]  # doc_id 截斷為 8 字
        assert "hello" in result.parts[0]


class TestMergeParentAndChunks:
    def test_parent_inserted_before_chunk(self):
        chunk_id = "chunk-001"
        parent_id = "parent-001"
        chunks = [
            {"id": chunk_id, "content": "child text", "document_id": "doc1", "chunk_index": 1, "score": 0.9},
        ]
        parent_map = {
            chunk_id: {
                "id": parent_id,
                "content": "parent text",
                "document_id": "doc1",
                "chunk_index": 0,
                "score": 0.0,
            }
        }
        with patch("app.services.context_fitting.PARENT_DOC_ENABLED_CHECK", return_value=True):
            merged = merge_parent_and_chunks(chunks, parent_map)
        # parent 在 child 之前
        assert len(merged) == 2
        assert merged[0]["_is_parent"] is True
        assert merged[0]["content"] == "parent text"
        assert merged[1]["content"] == "child text"
        # citation 指向原 chunk
        assert merged[0]["_citation_chunk_id"] == chunk_id

    def test_parent_deduplication(self):
        """同一 parent 被多個 chunk 引用時只插入一次。"""
        parent_id = "parent-001"
        chunks = [
            {"id": "c1", "content": "child1", "document_id": "doc1", "chunk_index": 1, "score": 0.9},
            {"id": "c2", "content": "child2", "document_id": "doc1", "chunk_index": 2, "score": 0.8},
        ]
        parent_map = {
            "c1": {"id": parent_id, "content": "parent", "document_id": "doc1", "chunk_index": 0, "score": 0.0},
            "c2": {"id": parent_id, "content": "parent", "document_id": "doc1", "chunk_index": 0, "score": 0.0},
        }
        with patch("app.services.context_fitting.PARENT_DOC_ENABLED_CHECK", return_value=True):
            merged = merge_parent_and_chunks(chunks, parent_map)
        # parent 只出現一次
        parents = [m for m in merged if m.get("_is_parent")]
        assert len(parents) == 1

    def test_parent_different_document_not_merged(self):
        """parent 與 chunk 不同文件時不合併。"""
        chunks = [
            {"id": "c1", "content": "child", "document_id": "doc1", "chunk_index": 1, "score": 0.9},
        ]
        parent_map = {
            "c1": {"id": "p1", "content": "parent", "document_id": "doc2", "chunk_index": 0, "score": 0.0},
        }
        with patch("app.services.context_fitting.PARENT_DOC_ENABLED_CHECK", return_value=True):
            merged = merge_parent_and_chunks(chunks, parent_map)
        # parent 不同文件，不合併
        assert len(merged) == 1
        assert not merged[0].get("_is_parent")

    def test_no_parent_when_disabled(self):
        chunks = [
            {"id": "c1", "content": "child", "document_id": "doc1", "chunk_index": 1, "score": 0.9},
        ]
        parent_map = {
            "c1": {"id": "p1", "content": "parent", "document_id": "doc1", "chunk_index": 0, "score": 0.0},
        }
        with patch("app.services.context_fitting.PARENT_DOC_ENABLED_CHECK", return_value=False):
            merged = merge_parent_and_chunks(chunks, parent_map)
        assert len(merged) == 1
        assert not merged[0].get("_is_parent")


class TestExpandSiblings:
    def test_basic_expansion(self):
        chunks = [
            {"id": "c1", "content": "main", "document_id": "doc1", "chunk_index": 5, "score": 0.9},
        ]
        sibling_lookup = {
            "c1": [
                {"id": "s1", "content": "prev", "document_id": "doc1", "chunk_index": 4, "score": 0.0},
                {"id": "s2", "content": "next", "document_id": "doc1", "chunk_index": 6, "score": 0.0},
            ]
        }
        expanded = expand_siblings(chunks, sibling_lookup, window=1, score_discount=0.85)
        assert len(expanded) == 3
        assert expanded[0]["content"] == "main"
        assert expanded[1]["_is_sibling"] is True
        assert expanded[1]["score"] == 0.9 * 0.85  # discounted

    def test_sibling_deduplication(self):
        """同一 sibling 被多個 chunk 引用時只出現一次。"""
        chunks = [
            {"id": "c1", "content": "main1", "document_id": "doc1", "chunk_index": 5, "score": 0.9},
            {"id": "c2", "content": "main2", "document_id": "doc1", "chunk_index": 6, "score": 0.8},
        ]
        sibling_lookup = {
            "c1": [
                {"id": "s1", "content": "sib", "document_id": "doc1", "chunk_index": 6, "score": 0.0},
                {"id": "s2", "content": "sib2", "document_id": "doc1", "chunk_index": 4, "score": 0.0},
            ],
            "c2": [
                {"id": "s1", "content": "sib", "document_id": "doc1", "chunk_index": 5, "score": 0.0},
            ],
        }
        expanded = expand_siblings(chunks, sibling_lookup, window=1, score_discount=0.85)
        # c1 + s1(chunk_index=6) + s2(chunk_index=4) + c2 + s1(chunk_index=5)
        # 但 c2 的 sibling chunk_index=5 與 c1 重複（c1 已加入）
        # 所以 c2 的 sibling 會被去重
        all_indices = [(c["document_id"], c["chunk_index"]) for c in expanded]
        # 不應有重複
        assert len(all_indices) == len(set(all_indices))

    def test_citation_preserved(self):
        chunks = [
            {"id": "c1", "content": "main", "document_id": "doc1", "chunk_index": 5, "score": 0.9},
        ]
        sibling_lookup = {
            "c1": [
                {"id": "s1", "content": "prev", "document_id": "doc1", "chunk_index": 4, "score": 0.0},
            ]
        }
        expanded = expand_siblings(chunks, sibling_lookup, window=1, score_discount=0.85)
        # sibling 的 citation 指向原始命中 chunk
        sibling = [e for e in expanded if e.get("_is_sibling")][0]
        assert sibling["_citation_chunk_id"] == "c1"

    def test_no_sibling_when_empty(self):
        chunks = [
            {"id": "c1", "content": "main", "document_id": "doc1", "chunk_index": 5, "score": 0.9},
        ]
        expanded = expand_siblings(chunks, {}, window=1, score_discount=0.85)
        assert len(expanded) == 1