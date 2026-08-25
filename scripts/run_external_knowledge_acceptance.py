#!/usr/bin/env python3
"""Run the external KB acceptance gates against one immutable release binding.

The command validates the original handoff, consumes completed evidence from
outside that bundle, and records each gate's real exit status. It never promotes
a revision and never turns missing evidence into PASS.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_knowledge_acceptance_handoff import verify_bundle


def _external_binding_errors(
    binding: dict, paths: dict[str, Path], profile: str
) -> list[str]:
    errors: list[str] = []
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"missing:{name}")
    if errors:
        return errors
    try:
        runtime = json.loads(paths["runtime_manifest"].read_text(encoding="utf-8"))
        browser = json.loads(paths["browser_evidence"].read_text(encoding="utf-8"))
        operations = json.loads(
            paths["operations_evidence"].read_text(encoding="utf-8")
        )
        resources = json.loads(
            paths["resource_observation"].read_text(encoding="utf-8")
        )
        expected_release = {
            "image_digest": binding["backend_image_digest"],
            "frontend_image_digest": binding["frontend_image_digest"],
            "deployment_manifest_id": binding["deployment_manifest_id"],
        }
        for label, payload in (("runtime", runtime), ("browser", browser)):
            if any(
                payload.get(key) != value for key, value in expected_release.items()
            ):
                errors.append(f"{label}_release_binding_mismatch")
        expected_revision = {
            "revision_id": binding["revision_id"],
            "manifest_hash": binding["kb_manifest_hash"],
        }
        if any(browser.get(key) != value for key, value in expected_revision.items()):
            errors.append("browser_revision_binding_mismatch")
        if operations.get("image_digest") != binding["backend_image_digest"] or any(
            operations.get(key) != value for key, value in expected_revision.items()
        ):
            errors.append("operations_binding_mismatch")
        if resources.get("image_digest") != binding["backend_image_digest"]:
            errors.append("resource_image_binding_mismatch")
        if resources.get("deployment_profile") != profile:
            errors.append("resource_profile_mismatch")
        capacity_queries = json.loads(
            paths["capacity_queries"].read_text(encoding="utf-8")
        )
        shadow_queries = json.loads(paths["shadow_queries"].read_text(encoding="utf-8"))
        z5_seal = json.loads(paths["z5_seal"].read_text(encoding="utf-8"))
        if not isinstance(capacity_queries, list) or len(capacity_queries) < 20:
            errors.append("capacity_queries_below_20")
        if not isinstance(shadow_queries, list) or len(shadow_queries) < 30:
            errors.append("shadow_queries_below_30")
        if (
            not isinstance(z5_seal, dict)
            or int(z5_seal.get("question_count") or 0) < 200
            or len(z5_seal.get("domain_counts") or {}) < 4
            or not z5_seal.get("custodian")
        ):
            errors.append("z5_seal_incomplete")
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        errors.append("external_evidence_invalid_json_or_binding")
    return errors


def build_commands(
    binding: dict, paths: dict[str, Path], output_dir: Path, profile: str
) -> list[tuple[str, list[str]]]:
    common = [
        "--tenant-id",
        binding["tenant_id"],
        "--revision-id",
        binding["revision_id"],
    ]
    image = ["--image-digest", binding["backend_image_digest"]]
    output_dir = output_dir.resolve()
    return [
        (
            "KB-BL-01",
            [
                sys.executable,
                "scripts/eval_knowledge_baseline_gate.py",
                *common,
                *image,
                "--z5-seal",
                str(paths["z5_seal"]),
                "--output",
                str(output_dir / "baseline_gate.json"),
            ],
        ),
        (
            "KB-EVAL-01",
            [
                sys.executable,
                "scripts/eval_knowledge_evaluation_gate.py",
                *common,
                *image,
                "--output",
                str(output_dir / "evaluation_gate.json"),
            ],
        ),
        (
            "KB-CAP-01",
            [
                sys.executable,
                "scripts/profile_knowledge_capacity.py",
                *common,
                *image,
                "--queries",
                str(paths["capacity_queries"]),
                "--profile",
                profile,
                "--resource-observation",
                str(paths["resource_observation"]),
                "--output",
                str(output_dir / "capacity_gate.json"),
            ],
        ),
        (
            "KB-UX-01",
            [
                sys.executable,
                "scripts/eval_browser_acceptance_gate.py",
                *common,
                "--evidence",
                str(paths["browser_evidence"]),
                "--output",
                str(output_dir / "browser_gate.json"),
            ],
        ),
        (
            "KB-SHADOW-01",
            [
                sys.executable,
                "scripts/run_production_shadow.py",
                *common,
                *image,
                "--queries",
                str(paths["shadow_queries"]),
                "--runtime-manifest",
                str(paths["runtime_manifest"]),
                "--output",
                str(output_dir / "shadow_gate.json"),
            ],
        ),
        (
            "KB-OPS-01",
            [
                sys.executable,
                "scripts/eval_knowledge_operations_gate.py",
                *common,
                *image,
                "--evidence",
                str(paths["operations_evidence"]),
                "--output",
                str(output_dir / "operations_gate.json"),
            ],
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument(
        "--deployment-manifest",
        type=Path,
        default=ROOT / "artifacts/knowledge/deployment_manifest.json",
    )
    parser.add_argument("--browser-evidence", type=Path, required=True)
    parser.add_argument("--operations-evidence", type=Path, required=True)
    parser.add_argument("--runtime-manifest", type=Path, required=True)
    parser.add_argument("--shadow-queries", type=Path, required=True)
    parser.add_argument("--capacity-queries", type=Path, required=True)
    parser.add_argument("--resource-observation", type=Path, required=True)
    parser.add_argument("--z5-seal", type=Path, required=True)
    parser.add_argument(
        "--profile", choices=["lite", "team", "enterprise"], default="enterprise"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts/knowledge/external_acceptance_run",
    )
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    integrity = verify_bundle(args.bundle, args.deployment_manifest)
    if integrity["status"] != "INTEGRITY_PASS_NOT_ATTESTED":
        print("HANDOFF_INTEGRITY_FAIL")
        return 1
    paths = {
        "browser_evidence": args.browser_evidence.resolve(),
        "operations_evidence": args.operations_evidence.resolve(),
        "runtime_manifest": args.runtime_manifest.resolve(),
        "shadow_queries": args.shadow_queries.resolve(),
        "capacity_queries": args.capacity_queries.resolve(),
        "resource_observation": args.resource_observation.resolve(),
        "z5_seal": args.z5_seal.resolve(),
    }
    binding_errors = _external_binding_errors(integrity["binding"], paths, args.profile)
    if binding_errors:
        print("EVIDENCE_PREFLIGHT_FAIL: " + ", ".join(binding_errors))
        return 1
    if args.preflight_only:
        print("EVIDENCE_PREFLIGHT_PASS_NOT_EXECUTED")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for gate, command in build_commands(
        integrity["binding"], paths, args.output_dir, args.profile
    ):
        completed = subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True, check=False
        )
        results.append(
            {
                "gate": gate,
                "status": "PASS" if completed.returncode == 0 else "FAIL",
                "returncode": completed.returncode,
                "output_tail": (completed.stdout + completed.stderr)[-4000:],
            }
        )
    status = "PASS" if all(result["status"] == "PASS" for result in results) else "FAIL"
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "promoted": False,
        "binding": integrity["binding"],
        "results": results,
    }
    (args.output_dir / "orchestration.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(status)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
