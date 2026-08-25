import json

import pytest

from scripts.build_blind_z5_corpus import build_corpus_manifest, freeze_gt


def test_manifest_is_nonempty_path_free_and_overlap_checked(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "new.txt").write_text("new sealed content", encoding="utf-8")
    output = tmp_path / "manifest.json"

    build_corpus_manifest(corpus, output, custodian="qa-a", exclude_manifests=[])
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["documents"][0]["file"] == "new.txt"
    assert "path" not in payload["documents"][0]
    assert payload["custodian"] == "qa-a"

    excluded = tmp_path / "old.json"
    excluded.write_text(
        json.dumps({"documents": [{"sha256": payload["documents"][0]["sha256"]}]}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        build_corpus_manifest(
            corpus,
            tmp_path / "overlap.json",
            custodian="qa-a",
            exclude_manifests=[excluded],
        )


def test_freeze_rejects_empty_or_undersized_question_bank(tmp_path):
    questions = tmp_path / "questions.yaml"
    questions.write_text(
        'gt_frozen: false\ngt_frozen_at: ""\nintent_frozen: false\nquestions: []\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"corpus_snapshot_id": "snapshot", "documents": [{"sha256": "a" * 64}]}),
        encoding="utf-8",
    )
    attestation = tmp_path / "attestation.txt"
    attestation.write_text("independently reviewed", encoding="utf-8")

    with pytest.raises(SystemExit):
        freeze_gt(
            questions_path=questions,
            manifest_path=manifest,
            seal_path=tmp_path / "seal.json",
            custodian="qa-a",
            attestation_path=attestation,
            implementer="developer-b",
        )
    assert not (tmp_path / "seal.json").exists()


def test_freeze_rejects_same_custodian_and_implementer(tmp_path):
    with pytest.raises(SystemExit):
        freeze_gt(
            questions_path=tmp_path / "missing.yaml",
            manifest_path=tmp_path / "missing.json",
            seal_path=tmp_path / "seal.json",
            custodian="same-person",
            attestation_path=tmp_path / "missing.txt",
            implementer="SAME-PERSON",
        )
