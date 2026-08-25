#!/usr/bin/env python3
"""Verify an immutable external-acceptance handoff bundle.

This validates chain of custody only. A pristine template bundle is expected to
be NOT_ATTESTED and must never be reported as accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
IMAGE = re.compile(r"sha256:[0-9a-fA-F]{64}")
DEPLOYMENT = re.compile(r"dm-[0-9a-fA-F]{24}")
HASH = re.compile(r"[0-9a-fA-F]{64}")
REQUIRED_FILES = {
    "binding.json",
    "runtime_manifest.template.json",
    "browser_evidence.template.json",
    "operations_evidence.template.json",
    "capacity_resource_observation.template.json",
    "capacity_queries.template.json",
    "shadow_queries.template.json",
    "README.md",
}


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_bundle(bundle: Path, deployment_manifest: Path | None = None) -> dict:
    reasons: list[str] = []
    bundle = bundle.resolve()
    manifest_path = bundle / "handoff_manifest.json"
    if not manifest_path.is_file():
        return {"status": "FAIL", "reasons": ["handoff_manifest_missing"]}
    try:
        manifest = _read(manifest_path)
    except (OSError, ValueError):
        return {"status": "FAIL", "reasons": ["handoff_manifest_invalid_json"]}
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        reasons.append("handoff_manifest_schema_invalid")
    if (
        manifest.get("status") != "PREPARED_NOT_ATTESTED"
        or manifest.get("independent_evidence_present") is not False
    ):
        reasons.append("handoff_manifest_fail_closed_state_invalid")

    recorded = manifest.get("file_sha256") or {}
    if not isinstance(recorded, dict) or set(recorded) != REQUIRED_FILES:
        reasons.append("handoff_file_set_invalid")
    actual_files = {
        path.name
        for path in bundle.iterdir()
        if path.is_file() and path.name != manifest_path.name
    }
    if actual_files != REQUIRED_FILES:
        reasons.append("bundle_contains_missing_or_unrecorded_files")
    for name in REQUIRED_FILES:
        expected = recorded.get(name) if isinstance(recorded, dict) else None
        path = bundle / name
        if path.is_symlink() or not path.is_file() or not HASH.fullmatch(str(expected)):
            reasons.append(f"file_digest_record_invalid:{name}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            reasons.append(f"file_digest_mismatch:{name}")

    binding = manifest.get("binding") or {}
    try:
        UUID(str(binding.get("tenant_id") or ""))
        UUID(str(binding.get("revision_id") or ""))
    except ValueError:
        reasons.append("binding_uuid_invalid")
    if not HASH.fullmatch(str(binding.get("kb_manifest_hash") or "")):
        reasons.append("kb_manifest_hash_invalid")
    if not DEPLOYMENT.fullmatch(str(binding.get("deployment_manifest_id") or "")):
        reasons.append("deployment_manifest_id_invalid")
    for key in ("backend_image_digest", "frontend_image_digest"):
        if not IMAGE.fullmatch(str(binding.get(key) or "")):
            reasons.append(f"{key}_invalid")
    try:
        if _read(bundle / "binding.json") != binding:
            reasons.append("binding_file_mismatch")
        runtime = _read(bundle / "runtime_manifest.template.json")
        browser = _read(bundle / "browser_evidence.template.json")
        operations = _read(bundle / "operations_evidence.template.json")
        resources = _read(bundle / "capacity_resource_observation.template.json")
        expected = {
            "image_digest": binding.get("backend_image_digest"),
            "frontend_image_digest": binding.get("frontend_image_digest"),
            "deployment_manifest_id": binding.get("deployment_manifest_id"),
        }
        if any(runtime.get(key) != value for key, value in expected.items()):
            reasons.append("runtime_template_binding_mismatch")
        if any(browser.get(key) != value for key, value in expected.items()):
            reasons.append("browser_template_binding_mismatch")
        revision_expected = {
            "revision_id": binding.get("revision_id"),
            "manifest_hash": binding.get("kb_manifest_hash"),
        }
        if any(browser.get(key) != value for key, value in revision_expected.items()):
            reasons.append("browser_revision_binding_mismatch")
        if operations.get("image_digest") != binding.get("backend_image_digest") or any(
            operations.get(key) != value for key, value in revision_expected.items()
        ):
            reasons.append("operations_template_binding_mismatch")
        if resources.get("image_digest") != binding.get("backend_image_digest"):
            reasons.append("resource_template_binding_mismatch")
        for name in ("capacity_queries.template.json", "shadow_queries.template.json"):
            if _read(bundle / name) != []:
                reasons.append(f"query_template_not_empty:{name}")
    except (AttributeError, OSError, ValueError):
        reasons.append("template_json_invalid")

    if deployment_manifest is not None:
        try:
            deployment = _read(deployment_manifest)
            images = deployment.get("candidate_images") or {}
            if deployment.get("deployment_manifest_id") != binding.get(
                "deployment_manifest_id"
            ):
                reasons.append("current_deployment_manifest_id_mismatch")
            if (images.get("backend") or {}).get("image_id") != binding.get(
                "backend_image_digest"
            ):
                reasons.append("current_backend_image_mismatch")
            if (images.get("frontend") or {}).get("image_id") != binding.get(
                "frontend_image_digest"
            ):
                reasons.append("current_frontend_image_mismatch")
        except (AttributeError, OSError, ValueError):
            reasons.append("current_deployment_manifest_invalid")
    return {
        "schema_version": 1,
        "status": "INTEGRITY_PASS_NOT_ATTESTED" if not reasons else "FAIL",
        "accepted": False,
        "binding": binding,
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument(
        "--deployment-manifest",
        type=Path,
        default=ROOT / "artifacts/knowledge/deployment_manifest.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify_bundle(args.bundle, args.deployment_manifest)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(report["status"])
    return 0 if report["status"] == "INTEGRITY_PASS_NOT_ATTESTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
