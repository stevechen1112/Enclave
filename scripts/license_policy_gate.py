#!/usr/bin/env python3
"""Enforce prohibited production dependency licences with expiring exceptions."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROHIBITED_MARKERS = ("AGPL", "AFFERO", "SSPL", "GNU GENERAL PUBLIC LICENSE")


def _licence_text(distribution: importlib.metadata.Distribution) -> str:
    expression = distribution.metadata.get("License-Expression", "")
    if expression:
        return expression.upper()
    get_all = getattr(distribution.metadata, "get_all", None)
    classifiers = get_all("Classifier") if get_all else []
    licence_classifiers = [
        value for value in classifiers or [] if value.startswith("License ::")
    ]
    if licence_classifiers:
        return " | ".join(licence_classifiers).upper()
    return str(distribution.metadata.get("License", "")).upper()


def _locked_packages(lock_path: Path) -> set[str]:
    packages: set[str] = set()
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not line.startswith((" ", "\t", "#")) and "==" in stripped:
            packages.add(stripped.split("==", 1)[0].lower().replace("_", "-"))
    return packages


def evaluate(
    exceptions_path: Path,
    today: date | None = None,
    allowed_names: set[str] | None = None,
) -> dict:
    current_date = today or datetime.now(timezone.utc).date()
    policy = json.loads(exceptions_path.read_text(encoding="utf-8"))
    exceptions = {
        str(item["package"]).lower(): item for item in policy.get("exceptions", [])
    }
    errors: list[str] = []
    findings: list[dict[str, str]] = []

    production_packages = allowed_names or _locked_packages(
        ROOT / "requirements.lock.txt"
    )
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name") or "unknown")
        if name.lower().replace("_", "-") not in production_packages:
            continue
        licence = _licence_text(distribution)
        if not any(marker in licence for marker in PROHIBITED_MARKERS):
            continue
        exception = exceptions.get(name.lower())
        if exception is None:
            errors.append(f"prohibited_license_without_exception:{name}")
            status = "unapproved"
        else:
            required = ("owner", "reason", "ticket", "expires_at")
            if any(not exception.get(field) for field in required):
                errors.append(f"license_exception_incomplete:{name}")
                status = "invalid_exception"
            elif date.fromisoformat(str(exception["expires_at"])) < current_date:
                errors.append(f"license_exception_expired:{name}")
                status = "expired"
            else:
                status = "time_bounded_exception"
        findings.append(
            {"package": name, "version": distribution.version, "status": status}
        )

    return {
        "schema_version": 1,
        "gate": "LICENSE-POLICY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "findings": sorted(findings, key=lambda item: item["package"].lower()),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--exceptions", type=Path, default=ROOT / "config/license_exceptions.json"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/security/license_policy_gate.json",
    )
    args = parser.parse_args()
    report = evaluate(args.exceptions)
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
