"""Cloud OCR pipeline integration tests (CV-RF-01b enhancement arm).

Covers the opt-in cloud OCR fallback in parse_document:
- disabled by default (no CLOUD_OCR_PROVIDER) — zero cloud calls
- low primary yield triggers cloud transcription and relabels the artifact
- sufficient primary yield never calls the cloud
- cloud failure / no-better-yield keeps the original parse, with warnings
"""
from __future__ import annotations

import os
import uuid

import pytest

from app.services import cloud_ocr
from app.services.cloud_ocr import CloudOCRResult
from app.services.parse_pipeline import parse_document


@pytest.fixture
def scanned_pdf(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    return str(path)


@pytest.fixture
def native_low_yield(monkeypatch):
    """Force the native path with near-zero text (simulates a failed scan parse)."""
    monkeypatch.delenv("RAGFLOW_ENABLED", raising=False)
    monkeypatch.delenv("RAGFLOW_FORCE_PARSE", raising=False)
    monkeypatch.delenv("PARSER_CANARY", raising=False)
    from app.services.document_parser import DocumentParser
    monkeypatch.setattr(
        DocumentParser, "parse",
        staticmethod(lambda fp, ft: ("殘缺", {"parse_engine": "native/pdf", "quality_score": 0.3})),
    )


def _enable_cloud(monkeypatch, provider="gemini"):
    monkeypatch.setenv("CLOUD_OCR_PROVIDER", provider)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")


class TestCloudOCRConfig:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("CLOUD_OCR_PROVIDER", raising=False)
        assert cloud_ocr.is_enabled() is False

    def test_disabled_without_api_key(self, monkeypatch):
        monkeypatch.setenv("CLOUD_OCR_PROVIDER", "gemini")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert cloud_ocr.is_enabled() is False

    def test_unknown_provider_rejected(self, monkeypatch):
        monkeypatch.setenv("CLOUD_OCR_PROVIDER", "unknown-ocr")
        assert cloud_ocr.is_enabled() is False

    def test_default_models(self, monkeypatch):
        monkeypatch.delenv("CLOUD_OCR_MODEL", raising=False)
        assert cloud_ocr.model_for("gemini") == "gemini-3-flash-preview"
        assert cloud_ocr.model_for("mistral") == "mistral-ocr-latest"
        monkeypatch.setenv("CLOUD_OCR_MODEL", "custom-model")
        assert cloud_ocr.model_for("gemini") == "custom-model"


class TestParsePipelineCloudArm:
    def test_disabled_never_calls_cloud(self, monkeypatch, scanned_pdf, native_low_yield):
        monkeypatch.delenv("CLOUD_OCR_PROVIDER", raising=False)
        called = []
        monkeypatch.setattr(cloud_ocr, "transcribe", lambda *a, **k: called.append(1))
        text, metadata, artifact = parse_document(scanned_pdf, "pdf", uuid.uuid4())
        assert called == []
        assert artifact.parser == "native/pdf"
        assert "cloud_ocr" not in metadata

    def test_low_yield_adopts_cloud_result(self, monkeypatch, scanned_pdf, native_low_yield):
        _enable_cloud(monkeypatch)
        monkeypatch.setattr(cloud_ocr, "transcribe", lambda *a, **k: CloudOCRResult(
            text="補印發票切結書 完整轉錄內容" * 20,
            provider="gemini", model="gemini-3-flash-preview",
            pages=1, elapsed_ms=1200,
        ))
        text, metadata, artifact = parse_document(scanned_pdf, "pdf", uuid.uuid4())
        assert "補印發票切結書" in text
        assert artifact.parser == "cloud/gemini:gemini-3-flash-preview"
        assert artifact.ocr_used is True
        assert metadata["cloud_ocr"]["original_engine"] == "native/pdf"
        assert any(w.get("code") == "cloud_ocr_adopted" for w in artifact.warnings)

    def test_sufficient_yield_skips_cloud(self, monkeypatch, scanned_pdf):
        _enable_cloud(monkeypatch)
        monkeypatch.delenv("RAGFLOW_ENABLED", raising=False)
        from app.services.document_parser import DocumentParser
        monkeypatch.setattr(
            DocumentParser, "parse",
            staticmethod(lambda fp, ft: ("足夠多的文字" * 100, {"parse_engine": "native/pdf"})),
        )
        called = []
        monkeypatch.setattr(cloud_ocr, "transcribe", lambda *a, **k: called.append(1))
        text, metadata, artifact = parse_document(scanned_pdf, "pdf", uuid.uuid4())
        assert called == []
        assert artifact.parser == "native/pdf"

    def test_cloud_failure_keeps_original(self, monkeypatch, scanned_pdf, native_low_yield):
        _enable_cloud(monkeypatch)

        def boom(*a, **k):
            raise RuntimeError("http_500: upstream down")
        monkeypatch.setattr(cloud_ocr, "transcribe", boom)
        text, metadata, artifact = parse_document(scanned_pdf, "pdf", uuid.uuid4())
        assert text == "殘缺"
        assert artifact.parser == "native/pdf"
        assert any(w.get("code") == "cloud_ocr_failed" for w in artifact.warnings)

    def test_cloud_not_better_keeps_original(self, monkeypatch, scanned_pdf, native_low_yield):
        _enable_cloud(monkeypatch)
        monkeypatch.setattr(cloud_ocr, "transcribe", lambda *a, **k: CloudOCRResult(
            text="殘", provider="gemini", model="gemini-3-flash-preview",
            pages=1, elapsed_ms=800,
        ))
        text, metadata, artifact = parse_document(scanned_pdf, "pdf", uuid.uuid4())
        assert text == "殘缺"
        assert artifact.parser == "native/pdf"
        assert any(w.get("code") == "cloud_ocr_no_better_yield" for w in artifact.warnings)
        assert metadata["cloud_ocr"]["provider"] == "gemini"

    def test_non_scan_types_never_trigger(self, monkeypatch, tmp_path, native_low_yield):
        _enable_cloud(monkeypatch)
        docx = tmp_path / "doc.docx"
        docx.write_bytes(b"fake")
        called = []
        monkeypatch.setattr(cloud_ocr, "transcribe", lambda *a, **k: called.append(1))
        parse_document(str(docx), "docx", uuid.uuid4())
        assert called == []
