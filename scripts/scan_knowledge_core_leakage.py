#!/usr/bin/env python3
"""Fail when evaluation IDs or fixed customer answers enter core branches."""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = [ROOT / "app" / "services", ROOT / "app" / "api", ROOT / "app" / "agent"]
EXCLUDED = {ROOT / "app" / "services" / "structured_answers.py"}
CASE_ID = re.compile(r"\b(?:Blind\s*)?Z[1-9]\d*[-_]\d{2,}\b")
FIXED_CLIENTS = {"金正昌", "八策", "杏壺", "味特", "周秀蘭"}


def branch_literals(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, (ast.If, ast.IfExp, ast.Match, ast.comprehension)):
            continue
        subject = getattr(node, "test", None) or getattr(node, "subject", None) or node
        for child in ast.walk(subject):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                yield child.lineno, child.value


def main() -> int:
    findings = []
    for base in CORE:
        for path in base.rglob("*.py"):
            if path in EXCLUDED or "knowledge_packs" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError) as exc:
                findings.append({"file": str(path.relative_to(ROOT)), "line": 0, "reason": f"parse_error:{type(exc).__name__}"})
                continue
            for line, value in branch_literals(tree):
                if CASE_ID.search(value):
                    findings.append({"file": str(path.relative_to(ROOT)), "line": line, "reason": "evaluation_case_id_in_branch"})
                if any(client in value for client in FIXED_CLIENTS):
                    findings.append({"file": str(path.relative_to(ROOT)), "line": line, "reason": "fixed_client_value_in_branch"})
    report = {"schema_version": 1, "gate": "KB-BL-CORE-LEAKAGE", "generated_at": datetime.now(timezone.utc).isoformat(),
              "status": "PASS" if not findings else "FAIL", "findings": findings}
    output = ROOT / "artifacts" / "knowledge" / "core_leakage_last_run.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report["status"])
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
