"""Fail when an application-owned database session has no explicit RLS scope.

The check is deliberately static and conservative. Every direct SessionLocal or
MaintenanceSessionLocal call under app/ must either establish tenant/bypass
scope in the same function or appear in the small, reasoned exception catalog.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

SESSION_FACTORIES = {"SessionLocal", "MaintenanceSessionLocal"}
SCOPE_CALLS = {
    "apply_rls_context",
    "apply_rls_bypass",
    "_scope_tenant",
    "_apply_maintenance_scope",
}


@dataclass(frozen=True)
class Finding:
    path: str
    function: str
    factory: str
    line: int
    reason: str

    @property
    def key(self) -> str:
        return f"{self.path}:{self.function}:{self.factory}"


def _call_name(call: ast.Call) -> str | None:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _calls_without_nested_functions(node: ast.AST) -> Iterable[ast.Call]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, ast.Call):
            yield child
        yield from _calls_without_nested_functions(child)


def _function_findings(
    path: str, function: ast.FunctionDef | ast.AsyncFunctionDef
) -> list[Finding]:
    calls = list(_calls_without_nested_functions(function))
    names = {_call_name(call) for call in calls}
    is_scoped = bool(names & SCOPE_CALLS)
    findings = []
    for call in calls:
        factory = _call_name(call)
        if factory not in SESSION_FACTORIES or is_scoped:
            continue
        findings.append(
            Finding(
                path=path,
                function=function.name,
                factory=factory,
                line=call.lineno,
                reason="session factory has no explicit tenant or audited bypass scope",
            )
        )
    return findings


def scan_tree(app_root: Path, project_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for source_path in sorted(app_root.rglob("*.py")):
        relative = source_path.relative_to(project_root).as_posix()
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path)
        )
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                findings.extend(_function_findings(relative, node))
    return findings


def evaluate(app_root: Path, project_root: Path, exception_path: Path) -> dict:
    catalog = json.loads(exception_path.read_text(encoding="utf-8"))
    exceptions = catalog.get("exceptions", {})
    findings = scan_tree(app_root, project_root)
    unresolved = [finding for finding in findings if finding.key not in exceptions]
    used = {finding.key for finding in findings if finding.key in exceptions}
    stale = sorted(set(exceptions) - used)
    errors = [asdict(finding) | {"key": finding.key} for finding in unresolved]
    errors.extend(
        {"key": key, "reason": "stale exception no longer matches a session call"}
        for key in stale
    )
    return {
        "gate": "TENANT-SESSION-CONTEXT",
        "schema_version": 1,
        "unscoped_candidate_count": len(findings),
        "reviewed_exception_count": len(used),
        "errors": errors,
        "status": "PASS" if not errors else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--app-root", type=Path)
    parser.add_argument("--exceptions", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    app_root = (args.app_root or project_root / "app").resolve()
    exception_path = (
        args.exceptions or project_root / "config" / "tenant_session_exceptions.json"
    ).resolve()
    report = evaluate(app_root, project_root, exception_path)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
