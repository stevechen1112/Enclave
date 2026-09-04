from __future__ import annotations

import hashlib
import json

import pytest

from scripts.eval_input_truth_corpus import evaluate, load_truth_corpus


def _manifest(tmp_path, *, verified=True):
    source = tmp_path / "source.txt"
    source.write_text("確認壓力歸零後停機", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    cases = []
    for index in range(5):
        cases.append(
            {
                "id": f"case-{index}",
                "slice": "factory_speech",
                "evidence_class": "licensed_internal",
                "ground_truth_verified": verified,
                "parse_success": True,
                "reference": "確認壓力歸零後停機",
                "hypothesis": "確認壓力歸零後停機",
                "locator_complete": True,
                "source": {"path": "source.txt", "sha256": digest},
                "annotation": {
                    "annotator": "independent-reviewer",
                    "verified_at": "2026-09-04T00:00:00Z",
                    "method": "manual transcription from original source",
                },
            }
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "input-truth-corpus.v1",
                "corpus_id": "test-corpus",
                "requested_claim": "semantic",
                "required_slices": ["factory_speech"],
                "cases": cases,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest, source


def test_verified_truth_manifest_can_issue_a_semantic_result(tmp_path):
    manifest, _ = _manifest(tmp_path)

    report = evaluate(manifest)

    assert report["status"] == "PASS"
    assert report["corpus"]["manifest_sha256"]


def test_modified_source_invalidates_the_truth_evidence(tmp_path):
    manifest, source = _manifest(tmp_path)
    source.write_text("來源已被修改", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_truth_corpus(manifest)


def test_verified_truth_requires_independent_annotation_metadata(tmp_path):
    manifest, _ = _manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["cases"][0]["annotation"] = {}
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="requires annotator"):
        load_truth_corpus(manifest)
