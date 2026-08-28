from __future__ import annotations

from scripts.prepare_p5_grounded_fixture import (
    _chat_is_grounded,
    _search_has_marker,
)


def test_search_marker_must_exist_in_retrieved_content():
    assert _search_has_marker(
        {"results": [{"content": "Procedure P5-SOP-RESET-042"}]},
        "P5-SOP-RESET-042",
    )
    assert not _search_has_marker(
        {"results": [{"content": "unrelated recovery data"}]},
        "P5-SOP-RESET-042",
    )


def test_grounded_chat_requires_answer_and_sources():
    assert _chat_is_grounded({"answer": "先確認壓力歸零", "sources": [{"id": "1"}]})
    assert not _chat_is_grounded({"answer": "無資料", "sources": []})
