from __future__ import annotations

import importlib.util
import io
import tarfile
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_drill():
    spec = importlib.util.spec_from_file_location(
        "p4_isolated_restore_drill", ROOT / "scripts" / "p4_isolated_restore_drill.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_compose_prefix_keeps_each_env_file_separate():
    module = _load_drill()
    args = Namespace(
        env_file=[".env.staging", ".env.db-admin.staging"],
        compose_file="docker-compose.prod.yml",
    )
    assert module._compose_prefix(args) == [
        "docker",
        "compose",
        "--env-file",
        ".env.staging",
        "--env-file",
        ".env.db-admin.staging",
        "-f",
        "docker-compose.prod.yml",
    ]


def test_relative_artifact_paths_are_rooted_in_repository():
    module = _load_drill()
    assert module._repo_path("backups/p4") == (ROOT / "backups" / "p4").resolve()


def test_object_archive_blocks_path_traversal():
    module = _load_drill()
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        member = tarfile.TarInfo("../escape")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(module.DrillError, match="unsafe object archive"):
        module._safe_tar_members(data.getvalue())


def test_object_archive_blocks_credentials():
    module = _load_drill()
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        member = tarfile.TarInfo("uploads/.credentials/token.json")
        member.size = 2
        archive.addfile(member, io.BytesIO(b"{}"))
    with pytest.raises(module.DrillError, match="credential path"):
        module._safe_tar_members(data.getvalue())


def test_safe_object_inventory_counts_files():
    module = _load_drill()
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        member = tarfile.TarInfo("uploads/tenant/file.txt")
        member.size = 3
        archive.addfile(member, io.BytesIO(b"abc"))
    assert module._safe_tar_members(data.getvalue()) == (1, 3)


def test_disaster_recovery_consumes_canonical_backup_names_and_volume():
    script = (ROOT / "scripts" / "disaster-recovery.sh").read_text(encoding="utf-8")
    assert 'name "enclave_*.sql"' in script
    assert 'name "uploads_*.tgz"' in script
    assert "init-storage" in script
    assert "-v ON_ERROR_STOP=1" in script
    assert "worker-beat" in script
    assert "gateway" in script


def test_restore_drill_uses_actual_legacy_chunk_table_name():
    script = (ROOT / "scripts" / "p4_isolated_restore_drill.py").read_text(
        encoding="utf-8"
    )
    assert "FROM documentchunks" in script
    assert "FROM document_chunks" not in script
