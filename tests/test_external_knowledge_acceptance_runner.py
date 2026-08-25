import sys
from pathlib import Path

from scripts.run_external_knowledge_acceptance import build_commands


def test_all_external_commands_bind_same_candidate_and_revision(tmp_path):
    binding = {
        "tenant_id": "tenant-id",
        "revision_id": "revision-id",
        "backend_image_digest": "sha256:" + "a" * 64,
    }
    paths = {
        "capacity_queries": Path("capacity.json"),
        "resource_observation": Path("resources.json"),
        "browser_evidence": Path("browser.json"),
        "shadow_queries": Path("shadow.json"),
        "runtime_manifest": Path("runtime.json"),
        "operations_evidence": Path("operations.json"),
        "z5_seal": Path("z5-seal.json"),
    }
    commands = build_commands(binding, paths, tmp_path, "enterprise")
    assert [gate for gate, _ in commands] == [
        "KB-BL-01",
        "KB-EVAL-01",
        "KB-CAP-01",
        "KB-UX-01",
        "KB-SHADOW-01",
        "KB-OPS-01",
    ]
    for _gate, command in commands:
        assert command[0] == sys.executable
        assert command[command.index("--tenant-id") + 1] == "tenant-id"
        assert command[command.index("--revision-id") + 1] == "revision-id"
    image_commands = [command for gate, command in commands if gate != "KB-UX-01"]
    assert all(
        command[command.index("--image-digest") + 1] == binding["backend_image_digest"]
        for command in image_commands
    )
    baseline = commands[0][1]
    assert baseline[baseline.index("--z5-seal") + 1] == "z5-seal.json"
