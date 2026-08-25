import json
import uuid

import pytest

from scripts.prepare_knowledge_acceptance_handoff import prepare_bundle


def _deployment_manifest(path):
    payload = {
        "deployment_manifest_id": "dm-" + "a" * 24,
        "candidate_images": {
            "backend": {"image_id": "sha256:" + "b" * 64},
            "frontend": {"image_id": "sha256:" + "c" * 64},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_handoff_is_bound_but_never_self_attested(tmp_path):
    deployment = tmp_path / "deployment.json"
    _deployment_manifest(deployment)
    output = tmp_path / "handoff"
    manifest_path = prepare_bundle(
        deployment_manifest=deployment,
        output_dir=output,
        tenant_id=str(uuid.uuid4()),
        revision_id=str(uuid.uuid4()),
        kb_manifest_hash="d" * 64,
    )
    handoff = json.loads(manifest_path.read_text(encoding="utf-8"))
    browser = json.loads((output / "browser_evidence.template.json").read_text(encoding="utf-8"))
    assert handoff["status"] == "PREPARED_NOT_ATTESTED"
    assert handoff["independent_evidence_present"] is False
    assert browser["runner"]["independent_of_implementation"] is False
    assert browser["frontend_image_digest"] == "sha256:" + "c" * 64
    statuses = {
        row["status"]
        for rows in browser["personas"].values()
        for row in rows
    }
    assert statuses == {"NOT_RUN"}
    assert all(handoff["file_sha256"].values())


def test_handoff_refuses_to_overwrite_existing_evidence(tmp_path):
    deployment = tmp_path / "deployment.json"
    _deployment_manifest(deployment)
    output = tmp_path / "handoff"
    output.mkdir()
    (output / "existing.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="never overwritten"):
        prepare_bundle(
            deployment_manifest=deployment,
            output_dir=output,
            tenant_id=str(uuid.uuid4()),
            revision_id=str(uuid.uuid4()),
            kb_manifest_hash="d" * 64,
        )
