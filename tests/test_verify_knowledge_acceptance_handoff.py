import json
import uuid

from scripts.prepare_knowledge_acceptance_handoff import prepare_bundle
from scripts.verify_knowledge_acceptance_handoff import verify_bundle


def _deployment(path):
    payload = {
        "deployment_manifest_id": "dm-" + "a" * 24,
        "candidate_images": {
            "backend": {"image_id": "sha256:" + "b" * 64},
            "frontend": {"image_id": "sha256:" + "c" * 64},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _bundle(tmp_path):
    deployment = tmp_path / "deployment.json"
    _deployment(deployment)
    bundle = tmp_path / "bundle"
    prepare_bundle(
        deployment_manifest=deployment,
        output_dir=bundle,
        tenant_id=str(uuid.uuid4()),
        revision_id=str(uuid.uuid4()),
        kb_manifest_hash="d" * 64,
    )
    return bundle, deployment


def test_pristine_bundle_passes_integrity_without_claiming_acceptance(tmp_path):
    bundle, deployment = _bundle(tmp_path)
    report = verify_bundle(bundle, deployment)
    assert report["status"] == "INTEGRITY_PASS_NOT_ATTESTED"
    assert report["accepted"] is False
    assert report["reasons"] == []


def test_modified_template_fails_chain_of_custody(tmp_path):
    bundle, deployment = _bundle(tmp_path)
    (bundle / "shadow_queries.template.json").write_text(
        '[{"query": "tampered"}]', encoding="utf-8"
    )
    report = verify_bundle(bundle, deployment)
    assert report["status"] == "FAIL"
    assert "file_digest_mismatch:shadow_queries.template.json" in report["reasons"]


def test_different_candidate_manifest_fails_binding(tmp_path):
    bundle, deployment = _bundle(tmp_path)
    payload = json.loads(deployment.read_text(encoding="utf-8"))
    payload["candidate_images"]["backend"]["image_id"] = "sha256:" + "e" * 64
    deployment.write_text(json.dumps(payload), encoding="utf-8")
    report = verify_bundle(bundle, deployment)
    assert "current_backend_image_mismatch" in report["reasons"]
