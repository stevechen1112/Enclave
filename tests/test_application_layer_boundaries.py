"""Executable gates for the core / workflow / application dependency direction."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from app.packs.mka.manifest import MKA_MODULE_KEYS, build_mka_pack
from app.services.mka_module_seed import CANONICAL_MODULES


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
CATALOG_PATH = ROOT / "config" / "application_boundary_catalog.json"


def _catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.lineno, node.module))
    return imports


def test_boundary_catalog_has_disjoint_product_layers() -> None:
    catalog = _catalog()
    assert catalog["schema_version"] == 1
    core = set(catalog["core_capabilities"])
    workflow = set(catalog["workflow_capabilities"])
    assert core
    assert workflow
    assert core.isdisjoint(workflow)
    assert catalog["legacy_mka_aggregate"]["status"] == "frozen_pending_split"
    assert (
        catalog["legacy_mka_aggregate"]["new_application_registration"]
        == "dedicated_pack_required"
    )


def test_core_roots_do_not_import_application_implementation() -> None:
    catalog = _catalog()
    forbidden = tuple(catalog["forbidden_core_import_prefixes"])
    violations: list[str] = []
    for relative_root in catalog["core_roots"]:
        for path in (ROOT / relative_root).rglob("*.py"):
            for line, imported in _imports(path):
                if imported.startswith(forbidden):
                    violations.append(f"{path.relative_to(ROOT)}:{line}:{imported}")
    assert violations == []


def test_backend_pack_imports_are_owned_or_composed_only() -> None:
    allowlist = set(_catalog()["pack_composition_import_allowlist"])
    violations: list[str] = []
    for path in APP.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("app/packs/") or relative in allowlist:
            continue
        for line, imported in _imports(path):
            if imported.startswith("app.packs."):
                violations.append(f"{relative}:{line}:{imported}")
    assert violations == []


def test_frontend_pack_bundle_is_imported_only_by_composition_root() -> None:
    composition_root = _catalog()["frontend_bundle_composition_root"]
    violations: list[str] = []
    for path in (ROOT / "frontend" / "src").rglob("*.ts*"):
        relative = path.relative_to(ROOT).as_posix()
        if relative == composition_root or "/modules/mka/" in f"/{relative}":
            continue
        text = path.read_text(encoding="utf-8")
        if "modules/mka" in text or "./mka/" in text or "../mka/" in text:
            violations.append(relative)
    assert violations == []


def test_legacy_mka_aggregate_is_frozen_until_split() -> None:
    """A sixth scenario must be a dedicated Pack, not another MKA seed entry."""
    expected = tuple(_catalog()["legacy_mka_aggregate"]["module_keys"])
    seeded = tuple(spec["module_key"] for spec in CANONICAL_MODULES)
    manifest = build_mka_pack().manifest
    assert seeded == expected
    assert tuple(MKA_MODULE_KEYS) == expected
    assert manifest.module_keys == expected

