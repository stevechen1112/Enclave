#!/usr/bin/env python3
"""Compute deterministic source, schema and route identity for release builds."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.freeze_deployment_manifest import (
        deployment_manifest_id,
        deployment_records,
    )
except ModuleNotFoundError:  # Direct execution: python scripts/release_identity.py
    from freeze_deployment_manifest import deployment_manifest_id, deployment_records

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "app" / "db" / "migrations" / "versions"
ROUTE_CONTRACT = ROOT / "frontend" / "release-contract.json"


def _literal_assignment(tree: ast.Module, name: str) -> Any:
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return ast.literal_eval(node.value) if node.value is not None else None
            continue
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    return None


def migration_heads() -> list[str]:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in VERSIONS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _literal_assignment(tree, "revision")
        down_revision = _literal_assignment(tree, "down_revision")
        if isinstance(revision, str):
            revisions.add(revision)
        if isinstance(down_revision, str):
            parents.add(down_revision)
        elif isinstance(down_revision, (tuple, list)):
            parents.update(item for item in down_revision if isinstance(item, str))
    return sorted(revisions - parents)


def route_contract() -> tuple[list[str], str]:
    data = json.loads(ROUTE_CONTRACT.read_text(encoding="utf-8"))
    routes = data["canonical_routes"]
    encoded = json.dumps(routes, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return routes, hashlib.sha256(encoded).hexdigest()


def source_commit() -> str:
    # ``GITHUB_SHA`` identifies the workflow definition commit.  A release
    # builder may deliberately check out and package a different, reviewed
    # commit, so allow that exact source SHA to be supplied explicitly.
    override = os.getenv("ENCLAVE_SOURCE_COMMIT", "").strip()
    if override:
        return override
    override = os.getenv("GITHUB_SHA", "").strip()
    if override:
        return override
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def source_dirty() -> str:
    override = os.getenv("ENCLAVE_SOURCE_DIRTY", "").strip().lower()
    if override in {"true", "false"}:
        return override
    status_output = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    return "true" if status_output.strip() else "false"


def build_identity() -> dict[str, str]:
    heads = migration_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one migration head, got {heads}")
    _, contract_hash = route_contract()
    commit = source_commit()
    dirty = source_dirty()
    release_id = os.getenv("ENCLAVE_RELEASE_ID", "").strip() or (
        f"gh-{os.getenv('GITHUB_RUN_ID', 'local')}-{os.getenv('GITHUB_RUN_ATTEMPT', '1')}"
    )
    build_time = os.getenv("ENCLAVE_BUILD_TIME", "").strip() or datetime.now(
        timezone.utc
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "release_id": release_id,
        "source_commit": commit,
        "source_dirty": dirty,
        "build_time": build_time,
        "schema_head": heads[0],
        "route_contract_hash": contract_hash,
        "deployment_manifest_id": deployment_manifest_id(deployment_records()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()
    identity = build_identity()
    if args.github_output:
        for key, value in identity.items():
            print(f"{key}={value}")
    else:
        print(json.dumps(identity, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
