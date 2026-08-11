"""
MKA P1 — Interaction API + Scene API + TermDictionary + module-scoped retrieval 測試。
"""
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.scene_resolver import SceneResolver, SceneContext, get_scene_resolver
from app.services.term_dictionary import TermDictionaryService


# ── Scene Resolver ──

class TestSceneResolver:
    def test_resolve_equipment_qr(self):
        resolver = SceneResolver()
        scene = resolver.resolve(qr_token="eq:CNC-001")
        assert scene is not None
        assert scene.equipment_id == "CNC-001"
        assert scene.resolved_from == "qr"

    def test_resolve_work_order_qr(self):
        resolver = SceneResolver()
        scene = resolver.resolve(qr_token="wo:WO-2026-001")
        assert scene is not None
        assert scene.work_order_id == "WO-2026-001"

    def test_resolve_product_qr(self):
        resolver = SceneResolver()
        scene = resolver.resolve(qr_token="prod:PROD-001")
        assert scene is not None
        assert scene.product_id == "PROD-001"

    def test_resolve_barcode_part_number(self):
        resolver = SceneResolver()
        scene = resolver.resolve(barcode="123456789")
        assert scene is not None
        assert scene.part_number == "123456789"
        assert scene.resolved_from == "barcode"

    def test_resolve_explicit_part_number(self):
        resolver = SceneResolver()
        scene = resolver.resolve(barcode="PN:ABC-123")
        assert scene is not None
        assert scene.part_number == "ABC-123"

    def test_resolve_empty_returns_none(self):
        resolver = SceneResolver()
        assert resolver.resolve() is None
        assert resolver.resolve(qr_token="", barcode="") is None

    def test_prompt_injection_blocked(self):
        """QR token 含換行/分號等應被拒。"""
        resolver = SceneResolver()
        assert resolver.resolve(qr_token="eq:test\nINJECT") is None
        assert resolver.resolve(qr_token="eq:test'; DROP TABLE") is None
        assert resolver.resolve(qr_token='eq:test"<script>') is None

    def test_retrieval_filter(self):
        scene = SceneContext(equipment_id="CNC-001", part_number="PN-001")
        filt = scene.retrieval_filter
        assert filt["equipment_id"] == "CNC-001"
        assert filt["part_number"] == "PN-001"

    def test_retrieval_filter_empty(self):
        scene = SceneContext()
        assert scene.retrieval_filter == {}

    def test_to_dict(self):
        scene = SceneContext(equipment_id="CNC-001", resolved_from="qr")
        d = scene.to_dict()
        assert d["equipment_id"] == "CNC-001"
        assert d["resolved_from"] == "qr"
        assert "resolved_at" in d


# ── Term Dictionary Service ──

class TestTermDictionary:
    def test_correct_transcript_phonetic(self):
        """phonetic_hints 應修正誤聽。"""
        mock_db = MagicMock()
        mock_term = MagicMock()
        mock_term.term = "CNC-800"
        mock_term.aliases = []
        mock_term.phonetic_hints = ["CNC 八百"]
        mock_term.active = True

        # 設定 query 鏈：query → filter → filter → all
        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_filtered.all.return_value = [mock_term]
        mock_query.filter.return_value = mock_filtered
        mock_db.query.return_value = mock_query

        svc = TermDictionaryService(mock_db)
        corrected = svc.correct_transcript(uuid4(), "設備 CNC 八百 故障")
        assert "CNC-800" in corrected
        assert "CNC 八百" not in corrected

    def test_correct_transcript_alias(self):
        """aliases 應替換為正式 term。"""
        mock_db = MagicMock()
        mock_term = MagicMock()
        mock_term.term = "正昌機械"
        mock_term.aliases = ["正昌"]
        mock_term.phonetic_hints = []
        mock_term.active = True

        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_filtered.all.return_value = [mock_term]
        mock_query.filter.return_value = mock_filtered
        mock_db.query.return_value = mock_query

        svc = TermDictionaryService(mock_db)
        corrected = svc.correct_transcript(uuid4(), "正昌的報價")
        assert "正昌機械" in corrected

    def test_correct_transcript_no_match(self):
        """無匹配時不改動。"""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_filtered.all.return_value = []
        mock_query.filter.return_value = mock_filtered
        mock_db.query.return_value = mock_query

        svc = TermDictionaryService(mock_db)
        corrected = svc.correct_transcript(uuid4(), "正常文字")
        assert corrected == "正常文字"

    def test_search_terms(self):
        mock_db = MagicMock()
        mock_term = MagicMock()
        mock_term.term = "CNC-800"
        mock_term.aliases = []
        mock_term.phonetic_hints = []
        mock_term.active = True
        mock_term.category = "equipment"
        mock_term.scope = "global"
        mock_term.source = "manual"
        mock_term.id = uuid4()
        mock_term.tenant_id = uuid4()
        mock_term.last_verified_at = None

        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_filtered.all.return_value = [mock_term]
        mock_query.filter.return_value = mock_filtered
        mock_db.query.return_value = mock_query

        svc = TermDictionaryService(mock_db)
        results = svc.search_terms(uuid4(), "CNC")
        assert len(results) >= 1
        assert "CNC" in results[0]["term"]