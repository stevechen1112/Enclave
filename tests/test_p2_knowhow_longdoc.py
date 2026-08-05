"""
P2：Know-how 與長文件 — 單元測試。

涵蓋：
- P2-1 Know-how Card + draft isolation
- P2-2 SOP conflict detection + authority tier
- P2-3 Wiki Semantic Lint
- P2-4 PageIndex 長 manual
"""
import pytest
from unittest.mock import MagicMock

from app.services.knowhow_card import (
    KnowhowCard,
    KnowhowCardStatus,
    KnowhowCardManager,
    get_knowhow_manager,
)
from app.services.sop_conflict import (
    AuthorityTier,
    ConflictRecord,
    SOPConflictChecker,
    get_sop_conflict_checker,
    resolve_conflict_sop_wins,
)
from app.services.wiki_lint import (
    LintRule,
    LintSeverity,
    WikiLinter,
    get_wiki_linter,
)
from app.services.pageindex import (
    PageIndexBuilder,
    PageIndexRetriever,
    PageIndexTree,
    get_pageindex_builder,
    get_pageindex_retriever,
)


# ── P2-1 Know-how Card ──

class TestKnowhowCard:
    def test_create_draft(self):
        mgr = KnowhowCardManager()
        card = mgr.create_draft(
            title="CNC 加工參數設定",
            summary="主軸轉速 8000 RPM",
            steps=["開機", "設定轉速", "開始加工"],
        )
        assert card.status == KnowhowCardStatus.DRAFT
        assert card.is_indexable is False  # draft 不可命中

    def test_draft_isolation(self):
        """draft 不可被 RetrievalFacade 命中。"""
        mgr = KnowhowCardManager()
        card = mgr.create_draft("測試", "摘要", ["步驟"])
        indexable = mgr.get_indexable_cards()
        assert card not in indexable  # draft 不在可索引列表

    def test_submit_for_review(self):
        mgr = KnowhowCardManager()
        card = mgr.create_draft("測試", "摘要", ["步驟"])
        card = mgr.submit_for_review(card.card_id)
        assert card.status == KnowhowCardStatus.PENDING_REVIEW

    def test_approve(self):
        mgr = KnowhowCardManager()
        card = mgr.create_draft("測試", "摘要", ["步驟"])
        mgr.submit_for_review(card.card_id)
        card = mgr.approve(card.card_id, reviewer="admin")
        assert card.status == KnowhowCardStatus.APPROVED
        assert card.is_indexable is True  # approved 可命中
        assert card.reviewer == "admin"

    def test_approve_idempotent(self):
        mgr = KnowhowCardManager()
        card = mgr.create_draft("測試", "摘要", ["步驟"])
        mgr.submit_for_review(card.card_id)
        card1 = mgr.approve(card.card_id, reviewer="admin")
        card2 = mgr.approve(card.card_id, reviewer="admin")
        assert card2.status == KnowhowCardStatus.APPROVED

    def test_reject(self):
        mgr = KnowhowCardManager()
        card = mgr.create_draft("測試", "摘要", ["步驟"])
        mgr.submit_for_review(card.card_id)
        card = mgr.reject(card.card_id, reviewer="admin", reason="不正確")
        assert card.status == KnowhowCardStatus.REJECTED
        assert card.is_indexable is False

    def test_revoke(self):
        mgr = KnowhowCardManager()
        card = mgr.create_draft("測試", "摘要", ["步驟"])
        mgr.submit_for_review(card.card_id)
        mgr.approve(card.card_id, reviewer="admin")
        card = mgr.revoke(card.card_id)
        assert card.status == KnowhowCardStatus.REVOKED
        assert card.is_indexable is False

    def test_supersede(self):
        mgr = KnowhowCardManager()
        card = mgr.create_draft("測試", "摘要", ["步驟"])
        mgr.submit_for_review(card.card_id)
        mgr.approve(card.card_id, reviewer="admin")
        card = mgr.supersede(card.card_id, "new-card-id")
        assert card.status == KnowhowCardStatus.SUPERSEDED
        assert card.is_indexable is False

    def test_approve_with_unresolved_conflict(self):
        mgr = KnowhowCardManager()
        card = mgr.create_draft("測試", "摘要", ["步驟"])
        mgr.submit_for_review(
            card.card_id,
            sop_conflicts=[{"type": "step_mismatch", "resolved": False}],
        )
        # 有未解決衝突，不允許核准
        with pytest.raises(ValueError, match="unresolved SOP conflicts"):
            mgr.approve(card.card_id, reviewer="admin")

    def test_approve_with_resolved_conflict(self):
        mgr = KnowhowCardManager()
        card = mgr.create_draft("測試", "摘要", ["步驟"])
        mgr.submit_for_review(
            card.card_id,
            sop_conflicts=[{"type": "step_mismatch", "resolved": True, "resolution": "sop_wins"}],
        )
        card = mgr.approve(card.card_id, reviewer="admin")
        assert card.status == KnowhowCardStatus.APPROVED

    def test_get_pending_review(self):
        mgr = KnowhowCardManager()
        card = mgr.create_draft("測試", "摘要", ["步驟"])
        mgr.submit_for_review(card.card_id)
        pending = mgr.get_pending_review()
        assert card in pending

    def test_card_to_dict(self):
        mgr = KnowhowCardManager()
        card = mgr.create_draft(
            title="測試",
            summary="摘要",
            steps=["步驟1"],
            applicable_equipment=["CNC-001"],
            risk_level="high",
        )
        d = card.to_dict()
        assert d["title"] == "測試"
        assert d["applicable_equipment"] == ["CNC-001"]
        assert d["risk_level"] == "high"
        assert d["status"] == "draft"


# ── P2-2 SOP Conflict ──

class TestSOPConflict:
    def test_authority_tier_order(self):
        assert AuthorityTier.SOP > AuthorityTier.APPROVED_KNOWHOW
        assert AuthorityTier.APPROVED_KNOWHOW > AuthorityTier.DRAFT_KNOWHOW
        assert AuthorityTier.DRAFT_KNOWHOW > AuthorityTier.RAW_DOCUMENT

    def test_step_mismatch_detection(self):
        checker = SOPConflictChecker()
        card = MagicMock()
        card.steps = ["開機", "設定轉速為 5000", "開始加工"]
        card.applicable_equipment = []
        card.cautions = []
        sop_docs = [{
            "title": "CNC 操作 SOP",
            "steps": ["開機", "設定轉速為 8000", "開始加工"],
            "applicable_equipment": [],
            "cautions": [],
        }]
        conflicts = checker.check_conflicts(card, sop_docs)
        # 步驟 2 內容相似但不一致
        step_conflicts = [c for c in conflicts if c.conflict_type == "step_mismatch"]
        assert len(step_conflicts) >= 1

    def test_equipment_mismatch(self):
        checker = SOPConflictChecker()
        card = MagicMock()
        card.steps = []
        card.applicable_equipment = ["CNC-001", "CNC-002", "CNC-003"]
        card.cautions = []
        sop_docs = [{
            "title": "CNC SOP",
            "steps": [],
            "applicable_equipment": ["CNC-001"],
            "cautions": [],
        }]
        conflicts = checker.check_conflicts(card, sop_docs)
        equip_conflicts = [c for c in conflicts if c.conflict_type == "equipment_mismatch"]
        assert len(equip_conflicts) >= 1

    def test_mutual_exclusion(self):
        checker = SOPConflictChecker()
        card = MagicMock()
        card.steps = []
        card.applicable_equipment = []
        card.cautions = ["可以高速運轉"]
        sop_docs = [{
            "title": "安全 SOP",
            "steps": [],
            "applicable_equipment": [],
            "cautions": ["禁止高速運轉"],
        }]
        conflicts = checker.check_conflicts(card, sop_docs)
        exclusion = [c for c in conflicts if c.conflict_type == "mutual_exclusion"]
        assert len(exclusion) >= 1

    def test_resolve_sop_wins(self):
        conflict = ConflictRecord(
            conflict_type="step_mismatch",
            sop_field="step[1]",
            knowhow_field="step[1]",
            sop_value="8000 RPM",
            knowhow_value="5000 RPM",
        )
        resolve_conflict_sop_wins(conflict)
        assert conflict.resolved is True
        assert conflict.resolution == "sop_wins"

    def test_no_conflict_when_compatible(self):
        checker = SOPConflictChecker()
        card = MagicMock()
        card.steps = ["開機", "設定參數"]
        card.applicable_equipment = ["CNC-001"]
        card.cautions = ["注意安全"]
        sop_docs = [{
            "title": "SOP",
            "steps": ["開機", "設定參數"],
            "applicable_equipment": ["CNC-001", "CNC-002"],
            "cautions": ["注意安全"],
        }]
        conflicts = checker.check_conflicts(card, sop_docs)
        assert conflicts == []


# ── P2-3 Wiki Lint ──

class TestWikiLint:
    def test_empty_content_warning(self):
        linter = WikiLinter()
        report = linter.lint("p1", "測試", "短")
        assert any(i.rule == LintRule.EMPTY_CONTENT for i in report.issues)

    def test_missing_sections(self):
        linter = WikiLinter()
        content = "# 標題\n這是一段足夠長的內容，用來通過空洞內容檢查。" * 5
        report = linter.lint("p1", "測試", content)
        missing = [i for i in report.issues if i.rule == LintRule.MISSING_SECTION]
        assert len(missing) >= 3  # 概述、步驟、注意事項

    def test_broken_reference(self):
        linter = WikiLinter()
        content = "## 概述\n[來源:doc-999]\n" + "內容" * 50
        report = linter.lint("p1", "測試", content, source_documents=[{"id": "doc-001"}])
        broken = [i for i in report.issues if i.rule == LintRule.BROKEN_REFERENCE]
        assert len(broken) >= 1

    def test_stale_reference(self):
        linter = WikiLinter()
        content = "## 概述\n[來源:doc-001]\n" + "內容" * 50
        report = linter.lint(
            "p1", "測試", content,
            source_documents=[{"id": "doc-001", "tombstoned_at": "2026-01-01"}],
        )
        stale = [i for i in report.issues if i.rule == LintRule.STALE_REFERENCE]
        assert len(stale) >= 1

    def test_format_error_unclosed_code(self):
        linter = WikiLinter()
        content = "## 概述\n```python\nprint('hello')\n" + "內容" * 50
        report = linter.lint("p1", "測試", content)
        fmt = [i for i in report.issues if i.rule == LintRule.FORMAT_ERROR]
        assert any("程式碼區塊未關閉" in i.message for i in fmt)

    def test_unmarked_conflict(self):
        linter = WikiLinter()
        content = "## 概述\n" + "正常內容" * 50
        report = linter.lint(
            "p1", "測試", content,
            known_conflicts=[{"type": "step_mismatch", "resolved": False}],
        )
        conflict_issues = [i for i in report.issues if i.rule == LintRule.UNMARKED_CONFLICT]
        assert len(conflict_issues) >= 1

    def test_pass_when_no_issues(self):
        linter = WikiLinter()
        content = (
            "## 概述\n這是概述內容，足夠長。\n"
            "## 步驟\n1. 第一步\n2. 第二步\n"
            "## 注意事項\n注意安全\n"
        )
        report = linter.lint("p1", "測試", content)
        assert report.passed is True
        assert report.error_count == 0

    def test_report_to_dict(self):
        linter = WikiLinter()
        report = linter.lint("p1", "測試", "短")
        d = report.to_dict()
        assert "issues" in d
        assert "passed" in d
        assert "error_count" in d


# ── P2-4 PageIndex ──

class TestPageIndex:
    def test_build_below_threshold(self):
        """頁數不足門檻，不建 tree。"""
        builder = PageIndexBuilder()
        chunks = [
            {"id": f"c{i}", "text": f"page {i} content", "metadata": {"page": i}}
            for i in range(1, 10)  # 9 頁
        ]
        tree = builder.build_from_chunks("doc-1", chunks, threshold=20)
        assert tree is None

    def test_build_above_threshold(self):
        """頁數達門檻，建 tree。"""
        builder = PageIndexBuilder()
        chunks = [
            {"id": f"c{i}", "text": f"page {i} content here", "metadata": {"page": i}}
            for i in range(1, 25)  # 24 頁
        ]
        tree = builder.build_from_chunks("doc-1", chunks, threshold=20)
        assert tree is not None
        assert tree.total_pages == 24
        assert len(tree.pages) == 24

    def test_page_node_chunk_ids(self):
        builder = PageIndexBuilder()
        chunks = [
            {"id": "c1", "text": "page 1", "metadata": {"page": 1}},
            {"id": "c2", "text": "page 1b", "metadata": {"page": 1}},
            {"id": "c3", "text": "page 2", "metadata": {"page": 2}},
        ]
        # 用低門檻測試
        tree = builder.build_from_chunks("doc-1", chunks, threshold=1)
        assert tree is not None
        page1 = tree.pages[0]
        assert len(page1.chunk_ids) == 2

    def test_section_ranges(self):
        builder = PageIndexBuilder()
        chunks = []
        for i in range(1, 25):
            title = f"## Section {i // 10 + 1}" if i % 10 == 1 else ""
            chunks.append({
                "id": f"c{i}",
                "text": f"{title}\npage {i} content",
                "metadata": {"page": i},
            })
        tree = builder.build_from_chunks("doc-1", chunks, threshold=20)
        assert tree is not None
        assert len(tree.section_ranges) >= 1

    def test_retriever_get_pages_by_number(self):
        retriever = PageIndexRetriever()
        tree = PageIndexTree(document_id="doc-1", total_pages=25)
        tree.pages = [
            type('P', (), {'page_number': i, 'chunk_ids': [f"c{i}"]})()
            for i in range(1, 26)
        ]
        pages = retriever.get_pages_for_query(tree, "請看第 5 頁")
        assert pages == [5]

    def test_retriever_get_pages_by_section(self):
        retriever = PageIndexRetriever()
        tree = PageIndexTree(document_id="doc-1", total_pages=25)
        tree.section_ranges = [
            {"title": "維護程序", "page_start": 10, "page_end": 15},
        ]
        pages = retriever.get_pages_for_query(tree, "維護程序怎麼做", max_pages=5)
        assert pages == [10, 11, 12, 13, 14]

    def test_retriever_get_chunks_for_pages(self):
        retriever = PageIndexRetriever()
        tree = PageIndexTree(document_id="doc-1", total_pages=5)
        from app.services.pageindex import PageNode
        tree.pages = [
            PageNode(page_number=1, chunk_ids=["c1", "c2"]),
            PageNode(page_number=2, chunk_ids=["c3"]),
            PageNode(page_number=3, chunk_ids=["c4", "c5"]),
        ]
        chunk_ids = retriever.get_chunks_for_pages(tree, [1, 3])
        assert set(chunk_ids) == {"c1", "c2", "c4", "c5"}

    def test_tree_to_dict(self):
        builder = PageIndexBuilder()
        chunks = [
            {"id": f"c{i}", "text": f"page {i}", "metadata": {"page": i}}
            for i in range(1, 25)
        ]
        tree = builder.build_from_chunks("doc-1", chunks, threshold=20)
        d = tree.to_dict()
        assert d["document_id"] == "doc-1"
        assert d["total_pages"] == 24
        assert d["schema"] == 1