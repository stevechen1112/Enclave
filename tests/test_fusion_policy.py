"""ADR-009 — FusionPolicy v1 單元測試。

可回歸情境（ADR 理由 2）：高分無檔名 compiled + 中分有檔名 document
→ document 必須勝出，compiled 必須被丟棄且計數。
"""
from __future__ import annotations

from app.gateway.contracts import ChunkResult
from app.gateway.fusion_policy import (
    AUTHORITY_COMPILED,
    AUTHORITY_EXTERNAL,
    AUTHORITY_PRIMARY,
    DOMAIN_GENERAL,
    DOMAIN_INTERNAL_RECORDS,
    FUSION_POLICY_VERSION,
    FusionPolicy,
    classify_authority,
    classify_query_domain,
    is_citable,
)


def _chunk(
    *,
    score: float,
    provider: str = "enclave",
    result_type: str = "chunk",
    filename: str | None = None,
    title: str | None = None,
    document_id: str | None = "doc-1",
) -> ChunkResult:
    meta = {}
    if filename is not None:
        meta["filename"] = filename
    if title is not None:
        meta["title"] = title
    return ChunkResult(
        id=f"{provider}-{score}",
        content="content",
        score=score,
        result_type=result_type,
        document_id=document_id,
        provider=provider,
        metadata=meta,
    )


class TestAuthorityClassification:
    def test_enclave_chunk_is_primary(self):
        assert classify_authority(_chunk(score=1.0)) == AUTHORITY_PRIMARY

    def test_weknora_wiki_is_compiled(self):
        r = _chunk(score=1.0, provider="weknora", result_type="wiki_page")
        assert classify_authority(r) == AUTHORITY_COMPILED

    def test_pipeshub_is_external(self):
        r = _chunk(score=1.0, provider="pipeshub", result_type="connector_record")
        assert classify_authority(r) == AUTHORITY_EXTERNAL


class TestCitability:
    def test_no_filename_no_title_not_citable(self):
        r = _chunk(score=0.99, provider="weknora", result_type="wiki_page",
                   document_id=None)
        assert not is_citable(r)

    def test_primary_with_filename_and_docid_citable(self):
        assert is_citable(_chunk(score=0.5, filename="營業稅繳款書.pdf"))

    def test_primary_without_document_id_not_citable(self):
        r = _chunk(score=0.5, filename="a.pdf", document_id=None)
        assert not is_citable(r)

    def test_compiled_with_stable_title_citable(self):
        r = _chunk(score=0.5, provider="weknora", result_type="wiki_page",
                   title="GRI Climate", document_id=None)
        assert is_citable(r)


class TestDomainClassification:
    def test_internal_records_keywords(self):
        assert classify_query_domain("營業稅繳款書的統一編號是多少？") == DOMAIN_INTERNAL_RECORDS
        assert classify_query_domain("哪些掃描件屬於財務憑證？") == DOMAIN_INTERNAL_RECORDS

    def test_general_query(self):
        assert classify_query_domain("什麼是光合作用？") == DOMAIN_GENERAL


class TestFusionPolicyApply:
    def test_r14_regression_high_score_non_citable_compiled_dropped(self):
        """R14 事故重現：高分無檔名 WeKnora 片段不得擠掉中分主文件。"""
        policy = FusionPolicy()
        results = [
            _chunk(score=0.99, provider="weknora", result_type="wiki_page",
                   document_id=None),  # 無檔名 → 不可引用
            _chunk(score=0.60, filename="營業稅繳款書(401).pdf"),
            _chunk(score=0.55, filename="費用申請流程.pdf", document_id="doc-2"),
        ]
        outcome = policy.apply(results, query="營業稅繳款書的統一編號是多少？", top_k=5)
        titles = [r.metadata["filename"] for r in outcome.results]
        assert "營業稅繳款書(401).pdf" in titles
        assert all("filename" in (r.metadata or {}) for r in outcome.results)
        assert outcome.dropped_non_citable == 1
        assert outcome.query_domain == DOMAIN_INTERNAL_RECORDS
        assert outcome.policy_version == FUSION_POLICY_VERSION

    def test_internal_records_primary_quota_before_compiled(self):
        """internal_records 域：有 title 的 compiled 也不得排在所有 primary 之前。"""
        policy = FusionPolicy()
        results = [
            _chunk(score=0.95, provider="weknora", result_type="wiki_page",
                   title="GRI Climate", document_id=None),
            _chunk(score=0.50, filename="補印發票切結書.pdf"),
        ]
        outcome = policy.apply(results, query="補印發票切結書需要填哪些欄位？", top_k=5)
        assert outcome.results[0].metadata["filename"] == "補印發票切結書.pdf"
        assert outcome.results[1].provider == "weknora"

    def test_general_domain_keeps_score_order(self):
        policy = FusionPolicy()
        results = [
            _chunk(score=0.50, filename="a.pdf"),
            _chunk(score=0.90, provider="weknora", result_type="wiki_page",
                   title="Wiki", document_id=None),
        ]
        outcome = policy.apply(results, query="什麼是光合作用？", top_k=5)
        assert outcome.query_domain == DOMAIN_GENERAL
        assert outcome.results[0].score >= outcome.results[1].score

    def test_internal_records_without_primary_keeps_compiled(self):
        """無 primary 命中時 compiled 仍可見（不得假綠式全丟）。"""
        policy = FusionPolicy()
        results = [
            _chunk(score=0.9, provider="weknora", result_type="wiki_page",
                   title="Wiki", document_id=None),
        ]
        outcome = policy.apply(results, query="合約相關背景", top_k=5)
        assert len(outcome.results) == 1

    def test_top_k_truncation_after_policy(self):
        policy = FusionPolicy()
        results = [
            _chunk(score=0.9 - i * 0.01, filename=f"f{i}.pdf", document_id=f"d{i}")
            for i in range(10)
        ]
        outcome = policy.apply(results, query="有哪些文件？", top_k=3)
        assert len(outcome.results) == 3
