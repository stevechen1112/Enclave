#!/usr/bin/env python3
"""Fail-closed reproducibility and tracked-secret checks for release inputs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

try:
    from scripts.release_source_gate import scan_secret_types
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from release_source_gate import scan_secret_types

ROOT = Path(__file__).resolve().parents[1]
ACTION_SHA = re.compile(r"^[^\s@]+@[0-9a-f]{40}(?:\s+#.*)?$")
FROM_LINE = re.compile(r"^\s*FROM\s+(\S+)", re.IGNORECASE)
IMAGE_LINE = re.compile(r"^\s*image:\s*(\S+)")
PINNED_REQUIREMENT = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?==[^\s]+$")


def _tracked_paths(root: Path) -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root, text=True, encoding="utf-8"
    )
    return [path for path in output.split("\0") if path]


def evaluate(root: Path, tracked_paths: list[str] | None = None) -> dict:
    errors: list[str] = []

    for workflow in sorted((root / ".github" / "workflows").glob("*.yml")):
        for number, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), 1
        ):
            stripped = line.strip()
            if stripped.startswith(("uses:", "- uses:")):
                value = stripped.split("uses:", 1)[1].strip()
                if not value.startswith("./") and not ACTION_SHA.fullmatch(value):
                    errors.append(f"action_not_sha_pinned:{workflow.name}:{number}")

    for dockerfile in (
        root / "Dockerfile",
        root / "frontend" / "Dockerfile",
        root / "docker" / "gateway.Dockerfile",
    ):
        for number, line in enumerate(
            dockerfile.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = FROM_LINE.match(line)
            if match and "@sha256:" not in match.group(1):
                errors.append(
                    f"base_image_not_digest_pinned:{dockerfile.name}:{number}"
                )

    image_files = [
        root / "docker-compose.prod.yml",
        root / "compose" / "sidecars.yml",
        *sorted((root / ".github" / "workflows").glob("*.yml")),
    ]
    for image_file in image_files:
        for number, line in enumerate(
            image_file.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = IMAGE_LINE.match(line)
            if not match:
                continue
            image = match.group(1)
            if "${IMAGE_PREFIX" in image:
                continue  # first-party image is bound by the deployment manifest gate
            if "@sha256:" not in image:
                relative = image_file.relative_to(root).as_posix()
                errors.append(f"image_not_digest_pinned:{relative}:{number}")

    locks = sorted(root.glob("requirements*.lock.txt"))
    if not locks:
        errors.append("python_lock_missing")
    for lock in locks:
        for number, line in enumerate(
            lock.read_text(encoding="utf-8").splitlines(), 1
        ):
            stripped = line.strip()
            if (
                stripped
                and not stripped.startswith(("#", "--"))
                and not line.startswith((" ", "\t"))
                and not PINNED_REQUIREMENT.fullmatch(stripped)
            ):
                errors.append(f"python_lock_unpinned:{lock.name}:{number}")

    dockerignore = root / ".dockerignore"
    if (
        dockerignore.is_file()
        and "!requirements.lock.txt"
        not in dockerignore.read_text(encoding="utf-8").splitlines()
    ):
        errors.append("python_lock_excluded_from_docker_context")

    trivy_ignore = root / ".trivyignore.yaml"
    if trivy_ignore.is_file():
        policy = yaml.safe_load(trivy_ignore.read_text(encoding="utf-8")) or {}
        for item in policy.get("vulnerabilities", []):
            identifier = str(item.get("id") or "unknown")
            statement = str(item.get("statement") or "")
            expiry = item.get("expired_at")
            if "Owner:" not in statement:
                errors.append(f"trivy_exception_owner_missing:{identifier}")
            if not expiry:
                errors.append(f"trivy_exception_expiry_missing:{identifier}")
            elif date.fromisoformat(str(expiry)) < datetime.now(timezone.utc).date():
                errors.append(f"trivy_exception_expired:{identifier}")

    npm_lock = root / "frontend" / "package-lock.json"
    try:
        lock_data = json.loads(npm_lock.read_text(encoding="utf-8"))
        if int(lock_data.get("lockfileVersion", 0)) < 3:
            errors.append("npm_lock_version_too_old")
    except (OSError, ValueError, json.JSONDecodeError):
        errors.append("npm_lock_missing_or_invalid")

    paths = tracked_paths if tracked_paths is not None else _tracked_paths(root)
    findings = scan_secret_types(root, paths)
    if findings:
        errors.append(f"tracked_high_confidence_secret_files:{len(findings)}")

    return {
        "schema_version": 1,
        "gate": "SUPPLY-CHAIN",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "secret_finding_types_by_path": findings,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/security/supply_chain_gate.json",
    )
    args = parser.parse_args()
    report = evaluate(ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "gate": report["gate"],
                "status": report["status"],
                "errors": report["errors"],
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
