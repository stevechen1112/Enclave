"""F4 QueryPlan 契約測試——規則分類＋複合拆解；禁止題號特判。"""
from __future__ import annotations

from app.services.query_plan import (
    build_query_plan,
    extract_mentioned_documents,
    is_inventory_query,
)


class TestInventory:
    def test_inventory_wants_catalog(self):
        plan = build_query_plan("目前庫內哪些文件屬於財務憑證？請列出檔名")
        assert plan.intent == "inventory"
        assert plan.wants_catalog
        assert "catalog" in plan.arms

    def test_fact_no_catalog(self):
        plan = build_query_plan("營業稅繳款書的統一編號是多少？")
        assert plan.intent == "fact"
        assert not plan.wants_catalog
        assert plan.arms == ["chunk"]

    def test_is_inventory_query_compat(self):
        assert is_inventory_query("有哪些合約文件") is True
        assert is_inventory_query("統一編號是多少") is False


class TestCompositeMultiHop:
    def test_composite_inventory_splits(self):
        plan = build_query_plan("入出境相關文件與人資相關文件各有哪些")
        assert plan.intent == "multi_hop"
        assert plan.wants_catalog
        assert len(plan.sub_queries) == 2
        assert any("入出境" in s for s in plan.sub_queries)
        assert any("人資" in s for s in plan.sub_queries)

    def test_no_question_id_special_case(self):
        # 換題幹仍應靠結構（連接詞＋各有）拆解，不靠 R15 等題號
        plan = build_query_plan("差勤手冊和掃描憑證各有哪些檔案")
        assert plan.intent == "multi_hop"
        assert len(plan.sub_queries) == 2


class TestTranslateAndCompare:
    def test_translate_intent(self):
        plan = build_query_plan("ETI Base Code 條款編號與標題對照")
        assert plan.intent == "translate"
        assert "chunk" in plan.arms
        assert "compiled" in plan.arms

    def test_compare_intent(self):
        plan = build_query_plan("比較兩份營業稅繳款書的差異")
        assert plan.intent == "compare"
        assert plan.wants_catalog

    def test_unanswerable_intent(self):
        plan = build_query_plan("這批文件裡有沒有提到火星殖民計畫的預算？")
        assert plan.intent == "unanswerable"
        assert plan.arms == []


class TestMentionedDocuments:
    def test_extract_single(self):
        assert extract_mentioned_documents(
            "根據文件《009_DOC003~3.pdf》，文件標題是什麼？"
        ) == ["009_DOC003~3.pdf"]

    def test_extract_multiple_dedup(self):
        q = "比較《A合約.pdf》與《B合約.pdf》，並對照《A合約.pdf》金額"
        assert extract_mentioned_documents(q) == ["A合約.pdf", "B合約.pdf"]

    def test_extract_corner_quotes_pdf(self):
        assert extract_mentioned_documents(
            "根目錄「行銷傳播企劃.pdf」主軸在談什麼？"
        ) == ["行銷傳播企劃.pdf"]

    def test_extract_corner_quotes_title_without_ext(self):
        assert extract_mentioned_documents(
            "「委託合約-八策品牌」與「合約-八策數位股份有限公司」是否同一份？"
        ) == ["委託合約-八策品牌", "合約-八策數位股份有限公司"]

    def test_plan_carries_corner_quote_documents(self):
        plan = build_query_plan("根目錄「行銷傳播企劃.pdf」主軸在談什麼？")
        assert plan.mentioned_documents == ["行銷傳播企劃.pdf"]

    def test_extract_bare_filename_pdf(self):
        assert extract_mentioned_documents(
            "杏壺報價.pdf 的報價金額或品項？"
        ) == ["杏壺報價.pdf"]

    def test_plan_carries_bare_filename(self):
        plan = build_query_plan("杏壺報價.pdf 的報價金額或品項？")
        assert plan.mentioned_documents == ["杏壺報價.pdf"]

    def test_no_mention(self):
        assert extract_mentioned_documents("統一編號是多少？") == []

    def test_plan_carries_mentioned_documents(self):
        plan = build_query_plan("根據文件《000_nueip 合約(1).pdf》，訂單日期是什麼？")
        assert plan.mentioned_documents == ["000_nueip 合約(1).pdf"]
        assert plan.to_dict()["mentioned_documents"] == ["000_nueip 合約(1).pdf"]


class TestCompareSplit:
    def test_three_way_顿号(self):
        from app.services.query_plan import _split_compare

        parts = _split_compare(
            "請比較醫美圈圈已用印行銷報價、巽耘視覺形象更新報價、立壕線板設計報價的總價，由高到低"
        )
        assert len(parts) == 3
        assert "立壕" in parts[2]

    def test_which_higher_with_yu(self):
        plan = build_query_plan("安可系統開發報價調整版與味特報價暨合約，哪份總價較高？")
        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2
        assert "安可" in plan.sub_queries[0]
        assert "味特" in plan.sub_queries[1]