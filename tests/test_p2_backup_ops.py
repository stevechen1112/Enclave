"""P2 backup: credential exclusion + safe tar extract."""
from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_ops():
    spec = importlib.util.spec_from_file_location(
        "ops_lifecycle", ROOT / "scripts" / "ops_lifecycle.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_exclude_credential_paths():
    mod = _load_ops()

    class TI:
        def __init__(self, name):
            self.name = name

    assert mod._exclude_credential_paths(TI("uploads/.credentials/x.json")) is None
    assert mod._exclude_credential_paths(TI("uploads/file.pdf")) is not None
    assert mod._exclude_credential_paths(TI("var/credentials/a.json")) is None


def test_safe_extract_blocks_traversal(tmp_path):
    mod = _load_ops()

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="../evil.txt")
        data = b"pwned"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    buf.seek(0)

    dest = tmp_path / "out"
    dest.mkdir()
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        with pytest.raises(ValueError, match="path traversal"):
            mod._safe_extract_tar(tar, dest)


def test_backup_sh_documents_canonical_entry():
    text = (ROOT / "scripts" / "backup.sh").read_text(encoding="utf-8")
    assert "ops_lifecycle.py backup" in text
    assert "--db-only" in text or "--direct" in text


def test_backup_full_uses_ops_lifecycle():
    text = (ROOT / "scripts" / "backup-full.sh").read_text(encoding="utf-8")
    assert "ops_lifecycle.py backup" in text
    assert "credentials" in text.lower()
