from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import asset_projection
from app.services.docling_ablation import DoclingParser, ParseResult
from app.services.document_parser import DocumentParser
from app.services.parse_pipeline import parse_document
from app.tasks import document_tasks as subject


def test_empty_spreadsheet_content_does_not_create_a_fake_chunk():
    assert subject._split_document_content("  \n ", "xlsx") == []


def test_short_spreadsheet_content_remains_one_structured_chunk(monkeypatch):
    monkeypatch.setattr(subject.settings, "TABLE_FULL_CHUNK_MAX_CHARS", 100)

    assert subject._split_document_content("品號,數量\nA-1,3", "csv") == [
        "品號,數量\nA-1,3"
    ]


def test_partial_embedding_response_fails_closed():
    with pytest.raises(RuntimeError, match="1 vectors for 2 chunks"):
        subject._require_embedding_cardinality(["a", "b"], [[0.1]])


def test_document_asset_state_updates_asset_and_revision_together(monkeypatch):
    asset = SimpleNamespace(status="processing")
    projection = SimpleNamespace(asset=asset)
    calls = []

    def project_document(db, document, *, ingestion_status):
        calls.append((db, document, ingestion_status))
        return projection

    monkeypatch.setattr(asset_projection, "project_document", project_document)
    db = object()
    document = object()

    result = subject._sync_document_asset_state(
        db,
        document,
        ingestion_status="failed",
        asset_status="failed",
    )

    assert result is projection
    assert asset.status == "failed"
    assert calls == [(db, document, "failed")]


def test_docling_adoption_does_not_reuse_native_confidence(monkeypatch, tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("短內容", encoding="utf-8")
    monkeypatch.setattr(subject.settings, "DOCLING_ENABLED", True)
    monkeypatch.setattr(DoclingParser, "is_available", lambda _self: True)
    monkeypatch.setattr(
        DoclingParser,
        "parse",
        lambda _self, _path, _type: ParseResult(
            text="Docling 產出的較長內容" * 20,
            tables=[{"name": "t1"}],
            elapsed_seconds=0.2,
        ),
    )
    monkeypatch.setattr(
        DocumentParser,
        "parse",
        staticmethod(
            lambda _path, _type: (
                "短內容",
                {"parse_engine": "native/text", "quality_score": 0.95},
            )
        ),
    )

    text, metadata, artifact = parse_document(str(source), "txt", uuid4())

    assert text.startswith("Docling")
    assert metadata["docling_adopted"] is True
    assert metadata["review_required"] is True
    assert artifact.confidence is None
    assert artifact.confidence_calibration_version == "unavailable"
