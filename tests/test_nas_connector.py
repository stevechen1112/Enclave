"""NAS local connector tests."""
from __future__ import annotations

from pathlib import Path

from app.services.nas_local_connector import scan_local_nas


def test_scan_local_nas(tmp_path: Path):
    f = tmp_path / "manual.txt"
    f.write_text("品質管理 ISO", encoding="utf-8")
    result = scan_local_nas(str(tmp_path))
    assert result["status"] == "completed"
    assert result["mode"] == "nas_local"
    assert len(result["resources"]) == 1
    assert result["resources"][0]["file_path"]
    assert len(result["acl_entries"]) == 1


def test_scan_missing_root():
    result = scan_local_nas("/nonexistent/nas/path/xyz")
    assert result["status"] == "error"
