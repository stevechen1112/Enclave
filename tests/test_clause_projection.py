"""F4 條款對照投影單元測試。"""
from __future__ import annotations

import json
import sys

from app.services.clause_projection import (
    format_projection_context,
    needs_clause_projection,
    _parse_clauses_json,
)


class TestNeedsProjection:
    def test_eti_filename(self):
        assert needs_clause_projection("006_ETI-Base-Code-Burmese.pdf", "") is True

    def test_burmese_sample(self):
        sample = "က" * 30 + " ethical trading "
        assert needs_clause_projection("x.pdf", sample) is True

    def test_plain_chinese_skip(self):
        assert needs_clause_projection("營業稅繳款書.pdf", "統一編號 83028948") is False


class TestWikiSyncHook:
    def test_upsert_calls_wiki_sync(self, monkeypatch):
        from uuid import uuid4
        from app.services import clause_projection as cp

        calls = []
        monkeypatch.setattr(
            cp, "sync_clause_projection_to_wiki", lambda **kw: calls.append(kw)
        )

        class Col:
            def __eq__(self, other):
                return True

        class DocumentArtifact:
            document_id = Col()
            artifact_type = Col()
            provider = Col()
            status = Col()

            def __init__(self, **kw):
                self.__dict__.update(kw)

        class FakeQ:
            def filter(self, *a, **k):
                return self

            def first(self):
                return None

        class FakeDB:
            def query(self, *a, **k):
                return FakeQ()

            def add(self, obj):
                pass

            def flush(self):
                pass

        import types

        fake_mod = types.ModuleType("app.models.knowledge_base")
        fake_mod.DocumentArtifact = DocumentArtifact
        monkeypatch.setitem(sys.modules, "app.models.knowledge_base", fake_mod)

        art = cp.upsert_clause_projection(
            db=FakeDB(),
            document_id=uuid4(),
            revision=1,
            clauses=[
                {
                    "clause_id": "1",
                    "title_zh": "就業",
                    "title_en": "Employment",
                    "summary_zh": "",
                    "source_excerpt": "",
                }
            ],
            source_chars=10,
            sync_wiki=True,
        )
        assert art is not None
        assert len(calls) == 1


class TestParseAndFormat:
    def test_parse_array(self):
        raw = json.dumps(
            [
                {
                    "clause_id": "1",
                    "title_en": "Employment is freely chosen",
                    "title_zh": "就業自由選擇",
                    "summary_zh": "禁止強迫勞動",
                    "source_excerpt": "…",
                }
            ],
            ensure_ascii=False,
        )
        clauses = _parse_clauses_json(raw)
        assert clauses[0]["clause_id"] == "1"
        assert "就業" in clauses[0]["title_zh"]

    def test_format_context(self):
        text = format_projection_context(
            [
                {
                    "filename": "ETI.pdf",
                    "clauses": [
                        {
                            "clause_id": "1",
                            "title_zh": "就業自由",
                            "title_en": "Employment freely chosen",
                            "summary_zh": "禁止強迫勞動",
                        }
                    ],
                }
            ]
        )
        assert "條款對照投影" in text
        assert "就業自由" in text
