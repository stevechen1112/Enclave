from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_sbom import generate_sbom_file


def test_sbom_contains_both_dependency_locks_and_pinned_images(tmp_path: Path) -> None:
    output = Path(generate_sbom_file(str(tmp_path)))
    sbom = json.loads(output.read_text(encoding="utf-8"))
    ecosystems = {
        property_["value"]
        for component in sbom["components"]
        for property_ in component.get("properties", [])
        if property_["name"] == "enclave:ecosystem"
    }
    assert ecosystems == {"python", "npm"}
    assert any(
        component.get("hashes")
        for component in sbom["components"]
        if component["type"] == "container"
    )
    metadata = {item["name"]: item["value"] for item in sbom["metadata"]["properties"]}
    assert len(metadata["enclave:python_lock_sha256"]) == 64
    assert len(metadata["enclave:npm_lock_sha256"]) == 64
