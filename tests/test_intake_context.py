from types import SimpleNamespace

import pytest

from app.services.intake_context import (
    IntakeContextError,
    apply_intake_metadata,
    parse_intake_context,
)
from app.tasks.document_tasks import _document_job_idempotency_key


def test_context_is_allowlisted_normalized_and_persisted_with_idempotency():
    context = parse_intake_context(
        '{"site":"  Tainan  ","equipment":"CNC-12","tags":["SOP","SOP","night"]}'
    )
    assert context == {
        "site": "Tainan",
        "equipment": "CNC-12",
        "tags": ["SOP", "night"],
    }
    asset = SimpleNamespace(metadata_json={"filename": "manual.pdf"})
    apply_intake_metadata(asset, context=context, idempotency_key="upload-123")
    assert asset.metadata_json["intake_context"] == context
    assert asset.metadata_json["intake_idempotency_key"] == "upload-123"


@pytest.mark.parametrize(
    "raw",
    [
        '["not-an-object"]',
        '{"customer_secret":"no"}',
        '{"tags":"not-a-list"}',
        '{"site":42}',
    ],
)
def test_context_rejects_uncontrolled_shapes(raw):
    with pytest.raises(IntakeContextError):
        parse_intake_context(raw)


def test_document_worker_reuses_persisted_intake_idempotency_key():
    asset = SimpleNamespace(metadata_json={"intake_idempotency_key": "stable-key"})
    assert _document_job_idempotency_key(asset, "doc-1", 1) == "stable-key"
    assert (
        _document_job_idempotency_key(SimpleNamespace(metadata_json={}), "doc-1", 2)
        == "document:doc-1:2"
    )
