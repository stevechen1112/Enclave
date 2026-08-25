#!/usr/bin/env python3
"""Freeze exact backend/frontend/gateway inputs without packaging workspace debris."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".dockerignore", "Dockerfile", "requirements.txt", "alembic.ini", "celery_worker.py",
    "docker-compose.prod.yml", "docker-compose.profiles.yml",
}
DIRECTORIES = {
    "backend": ("app", "docker", "configs"),
    "gateway": ("nginx", "compose"),
}
FRONTEND_ROOT_NAMES = {
    "Dockerfile", "nginx.conf", "package.json", "package-lock.json", "index.html",
    "eslint.config.js", "vite.config.ts", "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inspect_image(reference: str) -> dict[str, object]:
    raw = subprocess.check_output(
        ["docker", "image", "inspect", reference], cwd=ROOT, text=True
    )
    inspected = json.loads(raw)[0]
    repo_digests = sorted(inspected.get("RepoDigests") or [])
    return {
        "reference": reference,
        "image_id": inspected["Id"],
        "repo_digests": repo_digests,
        "size_bytes": inspected["Size"],
    }


def deployment_files() -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {"backend": [], "frontend": [], "gateway": []}
    for name in sorted(ROOT_FILES):
        path = ROOT / name
        if path.is_file():
            group = "gateway" if name.startswith("docker-compose") else "backend"
            groups[group].append(path)
    for group, directories in DIRECTORIES.items():
        for directory in directories:
            groups[group].extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
    frontend = ROOT / "frontend"
    groups["frontend"].extend(
        path for path in frontend.iterdir()
        if path.is_file() and path.name in FRONTEND_ROOT_NAMES
    )
    for directory in ("src", "public"):
        groups["frontend"].extend(path for path in (frontend / directory).rglob("*") if path.is_file())
    for group, paths in groups.items():
        groups[group] = sorted(
            {path for path in paths if "__pycache__" not in path.parts and path.suffix != ".pyc"},
            key=lambda path: path.as_posix(),
        )
    return groups


def deployment_manifest_id(records: list[dict], images: dict[str, dict[str, object]]) -> str:
    """Bind the identifier to exact files and built image identities."""
    file_rows = [
        f"file:{item['group']}:{item['path']}:{item['sha256']}:{item['bytes']}"
        for item in records
    ]
    image_rows = [
        f"image:{name}:{payload.get('image_id', '')}"
        for name, payload in sorted(images.items())
    ]
    canonical = "\n".join(file_rows + image_rows)
    return "dm-" + hashlib.sha256(canonical.encode()).hexdigest()[:24]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/knowledge/deployment_manifest.json")
    parser.add_argument("--backend-image")
    parser.add_argument("--frontend-image")
    args = parser.parse_args()
    groups = deployment_files()
    records = []
    for group, paths in groups.items():
        for path in paths:
            records.append({
                "group": group,
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": _sha(path),
                "bytes": path.stat().st_size,
            })
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=ROOT, text=True).splitlines()
    dirty_paths = set(
        subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD"], cwd=ROOT, text=True
        ).splitlines()
    )
    dirty_paths.update(
        subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=ROOT,
            text=True,
        ).splitlines()
    )
    deployment_paths = {item["path"] for item in records}
    deployment_dirty_paths = sorted(deployment_paths & dirty_paths)
    images = {}
    if args.backend_image:
        images["backend"] = _inspect_image(args.backend_image)
    if args.frontend_image:
        images["frontend"] = _inspect_image(args.frontend_image)
    payload = {
        "schema_version": 1,
        "gate": "DEPLOYMENT-MANIFEST",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "deployment_manifest_id": deployment_manifest_id(records, images),
        "file_count": len(records),
        "group_counts": {group: len(paths) for group, paths in groups.items()},
        "workspace_dirty_entry_count": len(dirty),
        "workspace_dirty_manifest_hash": hashlib.sha256("\n".join(sorted(dirty)).encode()).hexdigest(),
        "deployment_dirty_file_count": len(deployment_dirty_paths),
        "excluded_dirty_file_count": len(dirty_paths - deployment_paths),
        "deployment_dirty_paths": deployment_dirty_paths,
        "candidate_images": images,
        "records": records,
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(payload["deployment_manifest_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
