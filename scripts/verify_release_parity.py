#!/usr/bin/env python3
"""Verify backend and frontend release identity through the deployed edge."""

from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.request import urlopen

REQUIRED_ROUTES = {
    "/overview",
    "/ask",
    "/knowledge/assets",
    "/knowledge/new",
    "/knowledge/review",
    "/knowledge/quality",
    "/system/health",
    "/job",
}


def validate_parity(health: dict[str, Any], frontend: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    backend = health.get("release") or {}
    if health.get("status") != "ok":
        errors.append("backend health is not ok")
    if not backend.get("identifiable"):
        errors.append("backend release is not identifiable")
    if backend.get("source_dirty") != "false":
        errors.append("backend release was built from a dirty source tree")
    for key in (
        "release_id",
        "source_commit",
        "source_dirty",
        "schema_head",
        "route_contract_hash",
    ):
        if backend.get(key) != frontend.get(key):
            errors.append(
                f"{key} mismatch: backend={backend.get(key)!r} frontend={frontend.get(key)!r}"
            )
    routes = set(frontend.get("canonical_routes") or [])
    missing = sorted(REQUIRED_ROUTES - routes)
    if missing:
        errors.append(f"frontend route contract missing: {missing}")
    return errors


def _get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=20) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    health = _get_json(f"{base_url}/health")
    frontend = _get_json(f"{base_url}/release.json")
    errors = validate_parity(health, frontend)
    result = {
        "status": "PASS" if not errors else "HOLD",
        "base_url": base_url,
        "release_id": (health.get("release") or {}).get("release_id"),
        "source_commit": (health.get("release") or {}).get("source_commit"),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 3


if __name__ == "__main__":
    raise SystemExit(main())
