"""Shared fail-closed provenance checks for live P5 evidence runners."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_environment_evidence(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("environment evidence must contain a JSON object")
    evidence = dict(value)
    evidence["artifact_sha256"] = sha256_file(path)
    return evidence


def environment_binding_errors(
    evidence: dict[str, Any],
    *,
    source_commit: str | None = None,
    compose_project: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if evidence.get("status") != "PASS":
        errors.append("environment evidence is not PASS")
    if evidence.get("execution_class") != "live":
        errors.append("environment evidence is not live")
    if evidence.get("isolated_staging") is not True:
        errors.append("environment is not isolated staging")
    if evidence.get("co_resident_enclave_projects") != []:
        errors.append("environment has co-resident Enclave projects")
    observed_commit = str(evidence.get("source_commit") or "")
    if not _COMMIT.fullmatch(observed_commit):
        errors.append("environment source commit is invalid")
    if source_commit is not None and observed_commit != source_commit:
        errors.append("environment source commit mismatch")
    observed_project = str(evidence.get("compose_project") or "")
    if not observed_project:
        errors.append("environment Compose project is missing")
    if compose_project is not None and observed_project != compose_project:
        errors.append("environment Compose project mismatch")
    if not _SHA256.fullmatch(str(evidence.get("artifact_sha256") or "")):
        errors.append("environment artifact hash is invalid")
    runtime_images = evidence.get("runtime_images")
    if not isinstance(runtime_images, dict) or not runtime_images:
        errors.append("environment runtime image inventory is missing")
    else:
        for service, identity in runtime_images.items():
            if (
                not isinstance(identity, dict)
                or not str(identity.get("container") or "").strip()
                or not str(identity.get("container_id") or "").strip()
                or not str(identity.get("image_id") or "").strip()
            ):
                errors.append(f"environment runtime image is incomplete: {service}")
    return errors


def require_environment_binding(
    evidence: dict[str, Any],
    *,
    source_commit: str | None = None,
    compose_project: str | None = None,
) -> None:
    errors = environment_binding_errors(
        evidence,
        source_commit=source_commit,
        compose_project=compose_project,
    )
    if errors:
        raise ValueError("; ".join(errors))


def runtime_identity_matches_environment(
    evidence: dict[str, Any], identity: dict[str, Any]
) -> bool:
    container = str(identity.get("container") or "")
    container_id = str(identity.get("container_id") or "")
    image_id = str(identity.get("image_id") or "")
    runtime_images = evidence.get("runtime_images", {})
    if (
        not container
        or not container_id
        or not image_id
        or not isinstance(runtime_images, dict)
    ):
        return False
    return any(
        isinstance(row, dict)
        and str(row.get("container") or "") == container
        and str(row.get("container_id") or "") == container_id
        and str(row.get("image_id") or "") == image_id
        for row in runtime_images.values()
    )
