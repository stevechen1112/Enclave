"""Catalog 檔名 token：中文關鍵字必須能過濾（Blind Z3-067 根因）。"""
from __future__ import annotations

import re
from types import SimpleNamespace
from uuid import uuid4

from app.services.catalog_retrieval import CatalogRetriever, _filename_tokens


def test_filename_tokens_extracts_cjk_and_quoted():
    toks = _filename_tokens('這批資料裡，檔名或標題明顯出現「八策」的客戶／文件有哪些？')
    assert "八策" in toks
    # 虛詞／整句片語不得當過濾條件
    assert "文件" not in toks
    assert "哪些" not in toks
    assert all(len(t) <= 12 or re.search(r"[a-z0-9]", t) for t in toks)


def test_filename_tokens_unquoted_cjk_keyword():
    toks = _filename_tokens("請列出檔名含八策的文件")
    assert "八策" in toks
    assert "請列出檔名含八策的文件" not in toks


def test_filename_tokens_client_name_keeps_jinzhengchang():
    toks = _filename_tokens("金正昌報價提案談的是什麼、有無總價？")
    assert "金正昌" in toks
    assert "談的是" not in toks
    assert "有無" not in toks
    assert "報價" not in toks
    assert "提案" not in toks


def test_catalog_search_filters_by_cjk_filename_substring(monkeypatch):
    tenant = uuid4()
    docs = [
        SimpleNamespace(
            id=uuid4(),
            filename="「已用印」八策行銷報價單_醫美圈圈.pdf",
            genre="quote",
            tenant_id=tenant,
            status="completed",
            tombstoned_at=None,
            version=1,
        ),
        SimpleNamespace(
            id=uuid4(),
            filename="委託合約-八策品牌.pdf",
            genre="contract",
            tenant_id=tenant,
            status="completed",
            tombstoned_at=None,
            version=1,
        ),
        SimpleNamespace(
            id=uuid4(),
            filename="味特品牌研究企劃案報價暨合約.pdf",
            genre="contract",
            tenant_id=tenant,
            status="completed",
            tombstoned_at=None,
            version=1,
        ),
    ]

    class _Q:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *a, **k):
            return self

        def with_entities(self, *a, **k):
            return self

        def all(self):
            return [(row, row.version) for row in self._rows]

    class _Sess:
        def query(self, *_a, **_k):
            return _Q(docs)

        def close(self):
            return None

    monkeypatch.setattr("app.services.document_visibility.deny_set_allows", lambda *_a, **_k: True)
    hits = CatalogRetriever().search(
        tenant_id=tenant,
        query='檔名或標題明顯出現「八策」的文件有哪些？',
        top_k=50,
        authz=SimpleNamespace(
            tenant_id=tenant,
            subject_id=uuid4(),
            has_kb_admin=True,
            department_filter_ids=lambda: None,
        ),
        db=_Sess(),
    )
    names = {h.filename for h in hits}
    assert "「已用印」八策行銷報價單_醫美圈圈.pdf" in names
    assert "委託合約-八策品牌.pdf" in names
    assert "味特品牌研究企劃案報價暨合約.pdf" not in names
