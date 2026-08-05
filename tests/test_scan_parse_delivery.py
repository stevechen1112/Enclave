"""Scan parse delivery gate — no silent text_fallback completion."""
from __future__ import annotations

import uuid

import pytest

from app.services import cloud_ocr
from app.services.cloud_ocr import CloudOCRResult
from app.services.parse_pipeline import ScanParseDeliveryError, parse_document, _looks_dirty_ocr


@pytest.fixture
def scanned_pdf(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    return str(path)


def _enable_cloud(monkeypatch):
    monkeypatch.setenv("CLOUD_OCR_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def _fake_ragflow_empty_chunks(monkeypatch):
    """Simulate DeepDOC route that returns empty chunks → text_fallback label."""
    monkeypatch.setenv("RAGFLOW_ENABLED", "true")
    monkeypatch.setenv("RAGFLOW_DATASET_ID", "ds-test")
    monkeypatch.delenv("RAGFLOW_FORCE_PARSE", raising=False)
    monkeypatch.setenv("SCAN_PARSE_STRICT", "true")

    async def fake_parse(*args, **kwargs):
        from app.schemas.parse_artifact import ParseArtifact, ParseChunk
        return ParseArtifact(
            parser="native/text_fallback",
            version="1.0.0",
            chunks=[ParseChunk(text="優 利 資 源 整 合 股 份 有 限 公 司 " * 5, chunk_index=0)],
            ocr_used=False,
            warnings=[{"code": "ragflow_chunks_empty_used_text_fallback"}],
            metadata={"parse_route_intent": "ragflow_deepdoc"},
        )

    monkeypatch.setattr(
        "app.services.parse_pipeline._parse_via_ragflow", fake_parse,
    )


class TestDirtyHeuristic:
    def test_spaced_cjk_is_dirty(self):
        assert _looks_dirty_ocr("優 利 資 源 整 合 股 份 有 限 公 司 地址 測試") is True

    def test_clean_text_not_dirty(self):
        assert _looks_dirty_ocr("優利國際資源整合有限公司與由你人資管理顧問有限公司簽署合作備忘錄。" * 3) is False

    def test_broken_script_soup_is_dirty(self):
        # Shape of DeepDOC output on Burmese ETI page before cloud rescue.
        garbage = (
            "Ethical Trading Initiative 00 OII D。J J·J J·P Pll 88 P。J ?？。8 8 "
            "86386o P。9 P。 p0 3600:: 91 9. J G。P 9. 9 geae ep 0 s() pe 8= g GI "
            "6e:6mq960m: G. Jg G G g0 gaep: 39 3383= .？8898 : 026s: 38380903= "
        ) * 2
        assert _looks_dirty_ocr(garbage) is True


class TestDeliveryGate:
    def test_text_fallback_without_cloud_raises(self, monkeypatch, scanned_pdf):
        _fake_ragflow_empty_chunks(monkeypatch)
        monkeypatch.delenv("CLOUD_OCR_PROVIDER", raising=False)
        with pytest.raises(ScanParseDeliveryError, match="text_fallback"):
            parse_document(scanned_pdf, "pdf", uuid.uuid4())

    def test_text_fallback_rescued_by_cloud(self, monkeypatch, scanned_pdf):
        _fake_ragflow_empty_chunks(monkeypatch)
        _enable_cloud(monkeypatch)
        monkeypatch.setattr(cloud_ocr, "transcribe", lambda *a, **k: CloudOCRResult(
            text="優利國際資源整合有限公司與由你人資管理顧問有限公司" * 10,
            provider="gemini", model="gemini-3-flash-preview",
            pages=1, elapsed_ms=900,
        ))
        text, metadata, artifact = parse_document(scanned_pdf, "pdf", uuid.uuid4())
        assert "由你人資" in text
        assert artifact.parser.startswith("cloud/")
        assert artifact.ocr_used is True
        assert metadata["cloud_ocr"]["trigger"] == "text_fallback"

    def test_strict_off_allows_text_fallback_complete(self, monkeypatch, scanned_pdf):
        _fake_ragflow_empty_chunks(monkeypatch)
        monkeypatch.setenv("SCAN_PARSE_STRICT", "false")
        monkeypatch.delenv("CLOUD_OCR_PROVIDER", raising=False)
        text, metadata, artifact = parse_document(scanned_pdf, "pdf", uuid.uuid4())
        assert artifact.parser == "native/text_fallback"

    def test_missing_dataset_id_raises(self, monkeypatch, scanned_pdf):
        monkeypatch.setenv("RAGFLOW_ENABLED", "true")
        monkeypatch.setenv("RAGFLOW_DATASET_ID", "")
        monkeypatch.setenv("SCAN_PARSE_STRICT", "true")
        monkeypatch.delenv("CLOUD_OCR_PROVIDER", raising=False)
        # Without cloud rescue, empty dataset → exception → text_fallback label → gate
        with pytest.raises((ScanParseDeliveryError, RuntimeError)):
            parse_document(scanned_pdf, "pdf", uuid.uuid4())

    def test_dirty_long_text_triggers_cloud(self, monkeypatch, scanned_pdf):
        """Long but spaced-CJK text must trigger cloud even above min chars."""
        monkeypatch.delenv("RAGFLOW_ENABLED", raising=False)
        monkeypatch.setenv("SCAN_PARSE_STRICT", "false")
        _enable_cloud(monkeypatch)
        dirty = "優 利 資 源 整 合 股 份 有 限 公 司 " * 30  # >> 200 chars
        from app.services.document_parser import DocumentParser
        monkeypatch.setattr(
            DocumentParser, "parse",
            staticmethod(lambda fp, ft: (dirty, {"parse_engine": "native/pdf"})),
        )
        called = []

        def fake_transcribe(*a, **k):
            called.append(1)
            return CloudOCRResult(
                text="優利國際資源整合有限公司乾淨轉錄" * 20,
                provider="gemini", model="gemini-3-flash-preview",
                pages=1, elapsed_ms=500,
            )

        monkeypatch.setattr(cloud_ocr, "transcribe", fake_transcribe)
        text, metadata, artifact = parse_document(scanned_pdf, "pdf", uuid.uuid4())
        assert called == [1]
        assert metadata["cloud_ocr"]["trigger"] == "dirty_ocr_heuristic"
        assert "乾淨轉錄" in text


def _fake_ragflow_zero_chunk_pipeline(monkeypatch):
    """Real _parse_via_ragflow with adapter mocked to return zero chunks."""
    monkeypatch.setenv("RAGFLOW_ENABLED", "true")
    monkeypatch.setenv("RAGFLOW_DATASET_ID", "ds-test")
    monkeypatch.setenv("SCAN_PARSE_STRICT", "true")
    monkeypatch.setenv("RAGFLOW_PARSE_POLL_ATTEMPTS", "1")
    monkeypatch.setenv("RAGFLOW_PARSE_POLL_SLEEP_S", "0")
    monkeypatch.delenv("RAGFLOW_FORCE_PARSE", raising=False)

    async def fake_ingest(self, *a, **k):
        return {"status": "submitted", "ragflow_doc_ids": ["rf-1"]}

    async def fake_result(self, *a, **k):
        return {"status": "completed", "chunks": [], "confidence": 0.5}

    async def fake_cfg(self, *a, **k):
        return {"status": "ok", "layout_recognize": "DeepDOC", "chunk_method": "naive"}

    monkeypatch.setattr(
        "app.gateway.adapters.ragflow_http.RAGFlowHTTPAdapter.ingest", fake_ingest)
    monkeypatch.setattr(
        "app.gateway.adapters.ragflow_http.RAGFlowHTTPAdapter.get_parse_result", fake_result)
    monkeypatch.setattr(
        "app.gateway.adapters.ragflow_http.RAGFlowHTTPAdapter.get_dataset_config", fake_cfg)


def _boom_poppler_missing(fp, ft):
    raise ValueError(
        "文件解析品質不足: PDF 解析失敗: "
        "Unable to get page count. Is poppler installed and in PATH?"
    )


class TestEnvDependencyFailure:
    """Missing scan dependencies (poppler etc.) must not bypass cloud rescue
    nor escape as raw ValueError — ADR-010."""

    def test_native_fallback_failure_still_allows_cloud_rescue(self, monkeypatch, scanned_pdf):
        _fake_ragflow_zero_chunk_pipeline(monkeypatch)
        _enable_cloud(monkeypatch)
        from app.services.document_parser import DocumentParser
        monkeypatch.setattr(DocumentParser, "parse", staticmethod(_boom_poppler_missing))
        monkeypatch.setattr(cloud_ocr, "transcribe", lambda *a, **k: CloudOCRResult(
            text="優利國際資源整合有限公司 雲端救援轉錄" * 10,
            provider="gemini", model="gemini-3-flash-preview",
            pages=1, elapsed_ms=900,
        ))
        text, metadata, artifact = parse_document(scanned_pdf, "pdf", uuid.uuid4())
        assert "雲端救援轉錄" in text
        assert artifact.parser.startswith("cloud/")
        assert any(w.get("code") == "native_fallback_parse_failed"
                   for w in artifact.warnings if isinstance(w, dict))

    def test_native_fallback_failure_without_cloud_fails_actionable(self, monkeypatch, scanned_pdf):
        _fake_ragflow_zero_chunk_pipeline(monkeypatch)
        monkeypatch.delenv("CLOUD_OCR_PROVIDER", raising=False)
        from app.services.document_parser import DocumentParser
        monkeypatch.setattr(DocumentParser, "parse", staticmethod(_boom_poppler_missing))
        with pytest.raises(ScanParseDeliveryError, match="text_fallback"):
            parse_document(scanned_pdf, "pdf", uuid.uuid4())

    def test_scan_route_native_path_valueerror_reaches_delivery_gate(self, monkeypatch, scanned_pdf):
        """RAGFlow exception → native path → ValueError (poppler): scan route must
        funnel into text_fallback + delivery gate, not leak raw ValueError."""
        monkeypatch.setenv("RAGFLOW_ENABLED", "true")
        monkeypatch.setenv("RAGFLOW_DATASET_ID", "ds-test")
        monkeypatch.setenv("SCAN_PARSE_STRICT", "true")
        monkeypatch.delenv("RAGFLOW_FORCE_PARSE", raising=False)
        monkeypatch.delenv("CLOUD_OCR_PROVIDER", raising=False)

        async def fake_ingest(self, *a, **k):
            return {"status": "error", "error": "connection refused"}

        monkeypatch.setattr(
            "app.gateway.adapters.ragflow_http.RAGFlowHTTPAdapter.ingest", fake_ingest)
        from app.services.document_parser import DocumentParser
        monkeypatch.setattr(DocumentParser, "parse", staticmethod(_boom_poppler_missing))
        with pytest.raises(ScanParseDeliveryError, match="text_fallback"):
            parse_document(scanned_pdf, "pdf", uuid.uuid4())
