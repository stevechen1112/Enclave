from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.p5_evidence_binding import (
    load_environment_evidence,
    require_environment_binding,
    runtime_identity_matches_environment,
)


def _environment() -> dict:
    return {
        "status": "PASS",
        "execution_class": "live",
        "isolated_staging": True,
        "co_resident_enclave_projects": [],
        "source_commit": "a" * 40,
        "compose_project": "enclave-p5",
        "runtime_images": {
            "web": {
                "container": "enclave-p5-web-1",
                "container_id": "web-container-id",
                "image_id": "sha256:" + "b" * 64,
            }
        },
    }


def test_environment_file_is_hashed_and_bound(tmp_path: Path):
    path = tmp_path / "environment.json"
    path.write_text(json.dumps(_environment()), encoding="utf-8")
    evidence = load_environment_evidence(path)
    require_environment_binding(
        evidence, source_commit="a" * 40, compose_project="enclave-p5"
    )
    assert len(evidence["artifact_sha256"]) == 64
    assert runtime_identity_matches_environment(
        evidence,
        {
            "container": "enclave-p5-web-1",
            "container_id": "web-container-id",
            "image_id": "sha256:" + "b" * 64,
        },
    )


def test_environment_binding_rejects_shared_or_cross_release_evidence(
    tmp_path: Path,
):
    value = _environment()
    value["status"] = "HOLD"
    value["isolated_staging"] = False
    value["co_resident_enclave_projects"] = ["enclave"]
    path = tmp_path / "environment.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    evidence = load_environment_evidence(path)
    with pytest.raises(ValueError, match="not PASS"):
        require_environment_binding(
            evidence, source_commit="c" * 40, compose_project="other"
        )


def test_runtime_identity_requires_exact_container_and_image():
    evidence = _environment()
    assert runtime_identity_matches_environment(
        evidence,
        {
            "container": "enclave-p5-web-1",
            "container_id": "web-container-id",
            "image_id": "sha256:" + "c" * 64,
        },
    ) is False
