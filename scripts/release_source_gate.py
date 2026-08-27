#!/usr/bin/env python3
"""Fail closed unless a release is reproducibly bound to clean source and images."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.freeze_deployment_manifest import (
        deployment_files,
        deployment_manifest_id,
    )
except ModuleNotFoundError:  # Direct execution: python scripts/release_source_gate.py
    from freeze_deployment_manifest import deployment_files, deployment_manifest_id

ROOT = Path(__file__).resolve().parents[1]
RELEASE_TAG = re.compile(r"^(?:v\d|release-|rc-)")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private_key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("openai_key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
)
TOKEN_LIKE = re.compile(rb"[A-Za-z0-9_.@-]{8,}")
COMPROMISED_VALUE_SHA256S = {
    "0139815934c04f0c77e45c53a820eebd22390537f9ea89c55ecad2341cf1a9e1",
    "133febe9ec66cea32a1bef3a1cd93503faef8e0f7feedd9d4d1add6b1498be07",
    "3ef0803d63b30d6f95e67812b12a557bd6e8ded074dd630f9514b521315899cd",
}


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, encoding="utf-8", errors="replace"
    ).strip()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dirty_paths(root: Path) -> list[str]:
    """Return exact dirty paths, including untracked files, without directory collapsing."""
    output = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if not output:
        return []
    entries = output.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(entries):
        entry = entries[index]
        if not entry:
            index += 1
            continue
        status = entry[:2]
        path = entry[3:]
        paths.add(path.replace("\\", "/"))
        if "R" in status or "C" in status:
            index += 1
            if index < len(entries) and entries[index]:
                paths.add(entries[index].replace("\\", "/"))
        index += 1
    return sorted(paths)


def verify_records(
    root: Path,
    records: Sequence[dict],
    expected_paths: Iterable[str] | Mapping[str, str],
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for record in records:
        relative = str(record.get("path") or "")
        if not relative or relative in seen:
            errors.append("manifest_record_path_invalid_or_duplicate")
            continue
        seen.add(relative)
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            errors.append(f"manifest_record_outside_root:{relative}")
            continue
        if not candidate.is_file():
            errors.append(f"manifest_record_missing:{relative}")
            continue
        if _sha(candidate) != str(record.get("sha256") or ""):
            errors.append(f"manifest_record_hash_mismatch:{relative}")
        if candidate.stat().st_size != record.get("bytes"):
            errors.append(f"manifest_record_size_mismatch:{relative}")
        if isinstance(expected_paths, Mapping):
            expected_group = expected_paths.get(relative)
            if expected_group is not None and record.get("group") != expected_group:
                errors.append(f"manifest_record_group_mismatch:{relative}")
    expected = set(expected_paths)
    if seen != expected:
        missing = len(expected - seen)
        unexpected = len(seen - expected)
        errors.append(f"manifest_coverage_mismatch:missing={missing},unexpected={unexpected}")
    return errors


def scan_secret_types(root: Path, relative_paths: Iterable[str]) -> dict[str, list[str]]:
    """Return only secret type and path; never return matched credential material."""
    findings: dict[str, list[str]] = {}
    for relative in relative_paths:
        path = root / relative
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        matched = [name for name, pattern in SECRET_PATTERNS if pattern.search(data)]
        if any(
            hashlib.sha256(candidate).hexdigest() in COMPROMISED_VALUE_SHA256S
            for candidate in TOKEN_LIKE.findall(data)
        ):
            matched.append("compromised_credential")
        if matched:
            findings[relative] = matched
    return findings


def evaluate_release_source(
    root: Path,
    manifest: dict,
    *,
    require_tag: bool = True,
    require_images: bool = True,
) -> dict:
    errors: list[str] = []
    head = _git(root, "rev-parse", "HEAD")
    tags = sorted(filter(None, _git(root, "tag", "--points-at", "HEAD").splitlines()))
    worktree_dirty = dirty_paths(root)
    groups = deployment_files() if root == ROOT else {}
    expected_groups = {
        path.relative_to(root).as_posix(): group
        for group, paths in groups.items()
        for path in paths
    }
    expected_paths = sorted(expected_groups)
    records = manifest.get("records") if isinstance(manifest.get("records"), list) else []

    if str(manifest.get("source_commit") or "") != head:
        errors.append("source_commit_mismatch")
    if worktree_dirty:
        errors.append(f"worktree_not_clean:{len(worktree_dirty)}")
    if require_tag and not any(RELEASE_TAG.match(tag) for tag in tags):
        errors.append("release_tag_missing")
    if not expected_paths:
        errors.append("deployment_inventory_empty")
    errors.extend(verify_records(root, records, expected_groups))

    images = manifest.get("candidate_images") if isinstance(manifest.get("candidate_images"), dict) else {}
    if require_images:
        for name in ("backend", "frontend", "gateway"):
            image = images.get(name) if isinstance(images.get(name), dict) else {}
            if not IMAGE_ID.fullmatch(str(image.get("image_id") or "")):
                errors.append(f"candidate_image_invalid:{name}")

    expected_id = deployment_manifest_id(records)
    if str(manifest.get("deployment_manifest_id") or "") != expected_id:
        errors.append("deployment_manifest_id_mismatch")
    if int(manifest.get("deployment_dirty_file_count") or 0) != 0:
        errors.append("manifest_was_frozen_from_dirty_deployment_source")

    tracked_paths = filter(None, _git(root, "ls-files", "-z").split("\0"))
    secret_findings = scan_secret_types(root, tracked_paths)
    if secret_findings:
        errors.append(f"high_confidence_secret_files:{len(secret_findings)}")

    return {
        "schema_version": 1,
        "gate": "RELEASE-SOURCE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "source_commit": head,
        "release_tags": tags,
        "deployment_manifest_id": manifest.get("deployment_manifest_id"),
        "deployment_file_count": len(expected_paths),
        "dirty_file_count": len(worktree_dirty),
        "secret_finding_file_count": len(secret_findings),
        "secret_finding_types_by_path": secret_findings,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "artifacts/knowledge/deployment_manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/knowledge/release_source_gate_last_run.json",
    )
    parser.add_argument("--allow-untagged", action="store_true")
    parser.add_argument("--allow-missing-images", action="store_true")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        report = evaluate_release_source(
            ROOT,
            manifest,
            require_tag=not args.allow_untagged,
            require_images=not args.allow_missing_images,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": 1,
            "gate": "RELEASE-SOURCE",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "FAIL",
            "errors": [f"manifest_unreadable:{type(exc).__name__}"],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"gate": report["gate"], "status": report["status"], "errors": report["errors"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
