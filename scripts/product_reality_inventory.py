#!/usr/bin/env python3
"""Build a reproducible PRA0-Lite inventory without customer data.

The inventory separates surface presence from product validation. A route found
in production is evidence that the surface is deployed, not that its workflow
is usable or commercially ready.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "product_reality"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=20) as response:
        return json.load(response)


def _literal(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return ast.unparse(node)


def collect_feature_flags(root: Path) -> list[dict[str, Any]]:
    path = root / "app" / "config.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Settings":
            continue
        for item in node.body:
            if not isinstance(item, ast.AnnAssign) or not isinstance(
                item.target, ast.Name
            ):
                continue
            name = item.target.id
            if not (
                "ENABLED" in name
                or name.endswith("_MODE")
                or name.endswith("_REQUIRED")
                or name.endswith("_KILL_SWITCH")
                or name.endswith("_ALLOWLIST")
            ):
                continue
            rows.append(
                {
                    "key": name,
                    "declared_default": _literal(item.value),
                    "source": f"app/config.py:{item.lineno}",
                    "evidence_scope": "implementation",
                    "reality_level": "R1",
                }
            )
    return sorted(rows, key=lambda row: row["key"])


def collect_tasks(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((root / "app" / "tasks").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr != "task":
                    continue
                configured_name = next(
                    (
                        _literal(keyword.value)
                        for keyword in decorator.keywords
                        if keyword.arg == "name"
                    ),
                    None,
                )
                rows.append(
                    {
                        "task": configured_name or node.name,
                        "function": node.name,
                        "source": f"{path.relative_to(root).as_posix()}:{node.lineno}",
                        "evidence_scope": "implementation",
                        "reality_level": "R1",
                    }
                )
    return sorted(rows, key=lambda row: (row["task"], row["source"]))


def _router_prefixes(root: Path) -> dict[str, str]:
    path = root / "app" / "api" / "v1" / "api.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "include_router" or not node.args:
            continue
        router = node.args[0]
        if not (
            isinstance(router, ast.Attribute)
            and router.attr == "router"
            and isinstance(router.value, ast.Name)
        ):
            continue
        prefix = next(
            (_literal(item.value) for item in node.keywords if item.arg == "prefix"),
            "",
        )
        prefixes[router.value.id] = prefix if isinstance(prefix, str) else ""
    return prefixes


def collect_api_routes(root: Path) -> list[dict[str, Any]]:
    prefixes = _router_prefixes(root)
    rows: list[dict[str, Any]] = []
    methods = {"get", "post", "put", "patch", "delete", "options", "head"}
    endpoint_dir = root / "app" / "api" / "v1" / "endpoints"
    for path in sorted(endpoint_dir.glob("*.py")):
        module = path.stem
        tree = ast.parse(path.read_text(encoding="utf-8"))
        local_prefix = ""
        for statement in tree.body:
            if not isinstance(statement, ast.Assign) or not any(
                isinstance(target, ast.Name) and target.id == "router"
                for target in statement.targets
            ):
                continue
            if not isinstance(statement.value, ast.Call):
                continue
            local_prefix_value = next(
                (
                    _literal(keyword.value)
                    for keyword in statement.value.keywords
                    if keyword.arg == "prefix"
                ),
                "",
            )
            if isinstance(local_prefix_value, str):
                local_prefix = local_prefix_value
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not decorator.args:
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr not in methods:
                    continue
                declared = _literal(decorator.args[0])
                if not isinstance(declared, str):
                    continue
                full_path = f"/api/v1{prefixes.get(module, '')}{local_prefix}{declared}"
                full_path = re.sub(r"/+", "/", full_path)
                rows.append(
                    {
                        "method": func.attr.upper(),
                        "path": full_path,
                        "module": module,
                        "source": f"{path.relative_to(root).as_posix()}:{node.lineno}",
                        "surface_state": "declared_in_source",
                        "reality_level": "R1",
                    }
                )
    return sorted(rows, key=lambda row: (row["path"], row["method"], row["source"]))


def collect_frontend_routes(root: Path) -> list[dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    patterns = (
        re.compile(r"<Route\s+[^>]*path=[\"']([^\"']+)[\"']"),
        re.compile(r"\bpath\s*:\s*[\"']([^\"']+)[\"']"),
    )
    frontend = root / "frontend" / "src"
    for path in sorted(frontend.rglob("*.tsx")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            for pattern in patterns:
                for match in pattern.finditer(line):
                    route = match.group(1)
                    if not route.startswith("/"):
                        continue
                    source = f"{path.relative_to(root).as_posix()}:{line_number}"
                    rows[(route, source)] = {
                        "path": route,
                        "source": source,
                        "surface_state": "declared_in_source",
                        "reality_level": "R1",
                    }
    return sorted(rows.values(), key=lambda row: (row["path"], row["source"]))


def collect_packs(root: Path) -> list[dict[str, Any]]:
    backend = {
        path.parent.name for path in (root / "app" / "packs").glob("*/manifest.py")
    }
    frontend = {
        path.parent.name
        for path in (root / "frontend" / "src" / "modules").glob("*/routes.tsx")
    }
    knowledge = {
        path.stem
        for path in (root / "app" / "knowledge_packs").glob("*.py")
        if path.stem != "__init__"
    }
    keys = sorted(backend | frontend)
    rows = [
        {
            "key": key,
            "kind": "application_pack",
            "backend_manifest": key in backend,
            "frontend_bundle": key in frontend,
            "tenant_binding": "runtime_inventory_required",
            "product_validation": "UNVERIFIED",
            "reality_level": "R1",
        }
        for key in keys
    ]
    rows.extend(
        {
            "key": key,
            "kind": "knowledge_contribution",
            "backend_manifest": True,
            "frontend_bundle": False,
            "tenant_binding": "not_applicable",
            "product_validation": "UNVERIFIED",
            "reality_level": "R1",
        }
        for key in sorted(knowledge)
    )
    return rows


def collect_connectors(root: Path) -> list[dict[str, Any]]:
    path = root / "app" / "services" / "connector_schemas.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "CONNECTOR_SCHEMAS"
            for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Dict):
            keys.update(
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
    return [
        {
            "key": key,
            "implementation": "present",
            "live_credential_state": "UNVERIFIED",
            "reality_level": "R1",
            "source": "app/services/connector_schemas.py",
        }
        for key in sorted(keys)
    ]


def collect_providers(root: Path) -> list[dict[str, Any]]:
    path = root / "app" / "services" / "provider_runtime_health.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roles: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_LABELS"
            for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Dict):
            roles.update(
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
    return [
        {
            "role": role,
            "configuration_state": "runtime_probe_required",
            "reality_level": "R1",
            "source": "app/services/provider_runtime_health.py",
        }
        for role in sorted(roles)
    ]


def collect_claims(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = root / "docs" / "CAPABILITY_CLAIMS.md"
    section = "unclassified"
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"宣稱", "能力"}:
            continue
        rows.append(
            {
                "claim": cells[0],
                "declared_evidence": cells[1],
                "category": section,
                "current_release_state": "UNVERIFIED",
                "source": f"docs/CAPABILITY_CLAIMS.md:{line_number}",
            }
        )
    return rows


def documentation_findings(root: Path, production_release: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    readme = (root / "README.md").read_text(encoding="utf-8")
    match = re.search(r"目前狀態（(\d{4}-\d{2}-\d{2})）", readme)
    if match and match.group(1) != "2026-09-03":
        findings.append(
            {
                "id": "PRA-DOC-001",
                "severity": "P2",
                "summary": f"README status date is {match.group(1)}, not 2026-09-03",
                "source": "README.md",
            }
        )
    if production_release and production_release not in readme:
        findings.append(
            {
                "id": "PRA-DOC-002",
                "severity": "P2",
                "summary": "README does not identify the current production release",
                "source": "README.md",
            }
        )
    open_gates = (root / "docs" / "OPEN_GATES.md").read_text(encoding="utf-8")
    if (
        "剩餘 human gate：**1**" in open_gates
        and "剩餘人工閘門：外部滲透／法律／DR" in open_gates
    ):
        findings.append(
            {
                "id": "PRA-DOC-003",
                "severity": "P2",
                "summary": "OPEN_GATES reports one human gate and multiple external follow-ups",
                "source": "docs/OPEN_GATES.md",
            }
        )
    kq_plan = (
        root / "docs" / "KNOWLEDGE_ANSWER_RELIABILITY_TASK_PLAN_2026-09-03.md"
    ).read_text(encoding="utf-8")
    if (
        'status: "implemented, reviewed and deployed"' in kq_plan
        and "KQ0 不得開始" in kq_plan
    ):
        findings.append(
            {
                "id": "PRA-DOC-004",
                "severity": "P2",
                "summary": "KQ plan is deployed but still contains a pre-start prohibition",
                "source": "docs/KNOWLEDGE_ANSWER_RELIABILITY_TASK_PLAN_2026-09-03.md",
            }
        )
    return findings


def build_inventory(
    root: Path,
    *,
    base_url: str,
    runtime_manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    runtime_manifest = _json(runtime_manifest_path)
    public_health = _get_json(f"{base_url.rstrip('/')}/health")
    frontend_release = _get_json(f"{base_url.rstrip('/')}/release.json")
    backend_release = public_health.get("release") or {}
    identity_keys = (
        "release_id",
        "source_commit",
        "source_dirty",
        "schema_head",
        "route_contract_hash",
        "deployment_manifest_id",
    )
    release_errors: list[str] = []
    for key in identity_keys:
        expected = runtime_manifest.get(key)
        backend = backend_release.get(key)
        frontend = frontend_release.get(key)
        if expected != backend:
            release_errors.append(f"runtime_manifest_vs_backend:{key}")
        if key != "route_contract_hash" and expected != frontend:
            release_errors.append(f"runtime_manifest_vs_frontend:{key}")
        if key == "route_contract_hash" and backend != frontend:
            release_errors.append("backend_vs_frontend:route_contract_hash")

    capabilities = {
        "schema_version": "pra-capability-registry/v1",
        "api_routes": collect_api_routes(root),
        "frontend_routes": collect_frontend_routes(root),
        "background_tasks": collect_tasks(root),
        "feature_flags": collect_feature_flags(root),
        "packs": collect_packs(root),
        "connectors": collect_connectors(root),
        "providers": collect_providers(root),
        "interpretation": "Presence is implementation evidence only; workflow and product value remain independently graded.",
    }
    claims = {
        "schema_version": "pra-claim-registry/v1",
        "claims": collect_claims(root),
        "interpretation": "Historical claims are UNVERIFIED for the current release until linked to current evidence.",
    }
    findings = documentation_findings(root, runtime_manifest.get("release_id", ""))
    defects = {
        "schema_version": "pra-defect-register/v1",
        "findings": findings,
        "open_p0": 0,
        "open_p1": 0,
        "open_p2": sum(item["severity"] == "P2" for item in findings),
    }
    source_files = [
        root / "README.md",
        root / "docs" / "OPEN_GATES.md",
        root / "docs" / "CAPABILITY_CLAIMS.md",
        root / "app" / "api" / "v1" / "api.py",
        root / "app" / "config.py",
        root / "app" / "composition" / "packs.py",
    ]
    baseline = {
        "schema_version": "pra-baseline/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "HOLD"
        if release_errors
        else ("PASS_WITH_FINDINGS" if findings else "PASS"),
        "scope": "PRA0-Lite internal engineering inventory",
        "production": {
            "base_url": base_url,
            "runtime_manifest": runtime_manifest,
            "public_backend_release": backend_release,
            "public_frontend_release": frontend_release,
            "release_identity_errors": release_errors,
        },
        "inventory_counts": {
            key: len(value)
            for key, value in capabilities.items()
            if isinstance(value, list)
        },
        "source_hashes": {
            path.relative_to(root).as_posix(): _sha256(path) for path in source_files
        },
        "documentation_findings": [item["id"] for item in findings],
        "external_governance_is_development_gate": False,
    }
    return baseline, capabilities, claims, defects


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://kachu.tw")
    parser.add_argument(
        "--runtime-manifest",
        type=Path,
        default=ROOT
        / "artifacts"
        / "knowledge"
        / "KQ7_PRODUCTION_RUNTIME_MANIFEST.json",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    baseline, capabilities, claims, defects = build_inventory(
        ROOT,
        base_url=args.base_url,
        runtime_manifest_path=args.runtime_manifest,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write(args.output_dir / "PRA_BASELINE_MANIFEST.json", baseline)
    _write(args.output_dir / "PRA_CAPABILITY_REGISTRY.json", capabilities)
    _write(args.output_dir / "PRA_CLAIM_REGISTRY.json", claims)
    _write(args.output_dir / "PRA_DEFECT_REGISTER.json", defects)
    print(
        json.dumps(
            {"status": baseline["status"], **baseline["inventory_counts"]}, indent=2
        )
    )
    return 3 if baseline["production"]["release_identity_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
