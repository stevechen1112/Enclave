from __future__ import annotations

import json
from pathlib import Path

from scripts.tenant_session_context_gate import evaluate


def _write_catalog(path: Path, exceptions: dict[str, str] | None = None) -> None:
    path.write_text(
        json.dumps({"schema_version": 1, "exceptions": exceptions or {}}),
        encoding="utf-8",
    )


def test_gate_rejects_unscoped_session(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / "unsafe.py").write_text(
        "def load():\n    db = SessionLocal()\n    return db.query(Item).all()\n",
        encoding="utf-8",
    )
    catalog = tmp_path / "exceptions.json"
    _write_catalog(catalog)

    report = evaluate(app_root, tmp_path, catalog)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["key"] == "app/unsafe.py:load:SessionLocal"


def test_gate_accepts_tenant_scope_and_reviewed_global_exception(
    tmp_path: Path,
) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / "safe.py").write_text(
        "def scoped(tid):\n"
        "    db = SessionLocal()\n"
        "    apply_rls_context(db, tid)\n"
        "    return db.query(Item).all()\n\n"
        "def health():\n"
        "    db = SessionLocal()\n"
        "    return db.execute('SELECT 1')\n",
        encoding="utf-8",
    )
    catalog = tmp_path / "exceptions.json"
    _write_catalog(catalog, {"app/safe.py:health:SessionLocal": "SELECT 1 only"})

    report = evaluate(app_root, tmp_path, catalog)

    assert report["status"] == "PASS"
    assert report["reviewed_exception_count"] == 1


def test_gate_rejects_stale_exception(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / "safe.py").write_text("def noop():\n    return 1\n", encoding="utf-8")
    catalog = tmp_path / "exceptions.json"
    _write_catalog(catalog, {"app/safe.py:removed:SessionLocal": "obsolete"})

    report = evaluate(app_root, tmp_path, catalog)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["reason"].startswith("stale exception")
