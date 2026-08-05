"""拒答：問金額但召回無數字 → 應視為缺證據。"""
from __future__ import annotations

from app.services.refusal import amount_question_lacks_numeric_evidence


def test_amount_question_without_digits_lacks_evidence():
    assert amount_question_lacks_numeric_evidence(
        "捷報行銷提案報價的金額或方案價？",
        [{"content": "服務價目表\n品牌行銷是如何進行"}],
    )


def test_amount_question_with_tax_table_digits():
    assert not amount_question_lacks_numeric_evidence(
        "名片報價單價或數量？",
        [{"content": "未稅金額 940 \n含稅金額 987"}],
    )


def test_amount_question_with_price_has_evidence():
    assert not amount_question_lacks_numeric_evidence(
        "捷報行銷提案報價的金額？",
        [{"content": "專案合作報價：30,000 元／月"}],
    )


def test_amount_question_with_dollar_comma():
    assert not amount_question_lacks_numeric_evidence(
        "投放相關金額怎麼寫？",
        [{"content": "基本投放操作費 $30,000元/月"}],
    )


def test_non_amount_question_never_triggers():
    assert not amount_question_lacks_numeric_evidence(
        "這份合約的簽約雙方是誰？",
        [{"content": "甲方乙方條款"}],
    )


def test_guarantee_question_without_guarantee_word():
    from app.services.refusal import guarantee_question_lacks_evidence

    assert guarantee_question_lacks_evidence(
        "醫美圈圈已用印報價保證哪一天官網上線？",
        [{"content": "活動上線日：2024年1月15日"}],
    )


def test_guarantee_question_with_guarantee_in_evidence():
    from app.services.refusal import guarantee_question_lacks_evidence

    assert not guarantee_question_lacks_evidence(
        "合約保證哪個交付日？",
        [{"content": "乙方保證於2024年3月1日前交付"}],
    )
