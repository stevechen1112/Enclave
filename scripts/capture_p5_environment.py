#!/usr/bin/env python3
"""Capture fail-closed P5 host, release and runtime-image evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.hardware_inventory import (
    co_resident_enclave_projects,
    detect_hardware,
)

_CONTAINER = re.compile(r"^[A-Za-z0-9_.-]+$")


def _container_image(container: str) -> dict[str, str]:
    if not _CONTAINER.fullmatch(container):
        raise ValueError("container name contains unsupported characters")
    result = subprocess.run(
        ["docker", "inspect", container],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"cannot inspect {container}")
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError(f"unexpected inspect result for {container}")
    row = rows[0]
    if (row.get("State") or {}).get("Running") is not True:
        raise ValueError(f"runtime container is not running: {container}")
    return {
        "container": container,
        "configured_image": str((row.get("Config") or {}).get("Image") or ""),
        "image_id": str(row.get("Image") or ""),
    }


def capture(
    *, base_url: str, compose_project: str, containers: dict[str, str]
) -> dict[str, Any]:
    health_response = httpx.get(base_url.rstrip("/") + "/health", timeout=30)
    health_response.raise_for_status()
    health = health_response.json()
    release = health.get("release", {}) if isinstance(health, dict) else {}
    errors: list[str] = []
    if health.get("env") != "staging":
        errors.append("target environment is not staging")
    if release.get("identifiable") is not True:
        errors.append("release identity is not identifiable")
    source_commit = str(release.get("source_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        errors.append("release source commit is not a full Git SHA")
    co_resident = co_resident_enclave_projects(compose_project)
    if co_resident:
        errors.append("co-resident Enclave projects: " + ", ".join(co_resident))
    runtime_images = {
        service: _container_image(container) for service, container in containers.items()
    }
    return {
        "status": "PASS" if not errors else "HOLD",
        "execution_class": "live",
        "isolated_staging": not co_resident and health.get("env") == "staging",
        "compose_project": compose_project,
        "source_commit": source_commit,
        "release_id": str(release.get("release_id") or ""),
        "captured_at": datetime.now(UTC).isoformat(),
        "observed_hardware": detect_hardware(ROOT),
        "runtime_images": runtime_images,
        "co_resident_enclave_projects": co_resident,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--container", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-isolated-staging", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_staging:
        parser.error("--confirm-isolated-staging is required")
    containers: dict[str, str] = {}
    for value in args.container:
        service, separator, container = value.partition("=")
        if not separator or not service or not container or service in containers:
            parser.error("--container must be a unique service=container mapping")
        containers[service] = container
    try:
        evidence = capture(
            base_url=args.base_url,
            compose_project=args.compose_project,
            containers=containers,
        )
    except (OSError, RuntimeError, TypeError, ValueError, httpx.HTTPError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.chmod(args.output, 0o600)
    print(json.dumps({"status": evidence["status"], "errors": evidence["errors"]}))
    return 0 if evidence["status"] == "PASS" else 10


if __name__ == "__main__":
    raise SystemExit(main())
