#!/usr/bin/env python3
"""Generate a release-bound CycloneDX SBOM from committed dependency locks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
PYTHON_LOCK = ROOT / "requirements.lock.txt"
NPM_LOCK = ROOT / "frontend" / "package-lock.json"
IMAGE_FILES = (ROOT / "docker-compose.prod.yml", ROOT / "compose" / "sidecars.yml")
IMAGE = re.compile(r"^\s*image:\s*(\S+)", re.MULTILINE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _python_components() -> list[dict]:
    components: list[dict] = []
    for line in PYTHON_LOCK.read_text(encoding="utf-8").splitlines():
        if not line.startswith((" ", "\t", "#")) and "==" in line:
            name, version = line.strip().split("==", 1)
            purl = f"pkg:pypi/{name.lower().replace('_', '-')}@{version}"
            components.append(
                {
                    "type": "library",
                    "name": name,
                    "version": version,
                    "purl": purl,
                    "bom-ref": purl,
                    "properties": [{"name": "enclave:ecosystem", "value": "python"}],
                }
            )
    return components


def _npm_components() -> list[dict]:
    data = json.loads(NPM_LOCK.read_text(encoding="utf-8"))
    components: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for path, package in data.get("packages", {}).items():
        if not path or not isinstance(package, dict):
            continue
        name = str(package.get("name") or path.rsplit("node_modules/", 1)[-1])
        version = str(package.get("version") or "")
        if not name or not version or (name, version) in seen:
            continue
        seen.add((name, version))
        purl = f"pkg:npm/{quote(name, safe='')}@{version}"
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": purl,
                "bom-ref": purl,
                "properties": [{"name": "enclave:ecosystem", "value": "npm"}],
            }
        )
    return components


def _image_components() -> list[dict]:
    references: set[str] = set()
    for path in IMAGE_FILES:
        for match in IMAGE.finditer(path.read_text(encoding="utf-8")):
            reference = match.group(1).rstrip("}")
            if "${IMAGE_PREFIX" not in reference:
                references.add(reference.split(":-", 1)[-1])
    for name in ("backend", "frontend", "gateway"):
        digest = os.getenv(f"{name.upper()}_IMAGE_DIGEST", "").strip()
        if digest:
            references.add(f"{os.getenv('IMAGE_PREFIX', 'enclave')}/{name}@{digest}")

    components: list[dict] = []
    for reference in sorted(references):
        digest = reference.rsplit("@sha256:", 1)[-1] if "@sha256:" in reference else ""
        tagged_name = reference.split("@", 1)[0]
        name = (
            tagged_name.rsplit(":", 1)[0]
            if ":" in tagged_name.rsplit("/", 1)[-1]
            else tagged_name
        )
        component = {
            "type": "container",
            "name": name,
            "version": f"sha256:{digest}" if digest else reference,
            "bom-ref": f"pkg:docker/{name}@sha256:{digest}"
            if digest
            else f"pkg:docker/{name}",
        }
        if digest:
            component["hashes"] = [{"alg": "SHA-256", "content": digest}]
        components.append(component)
    return components


def generate_sbom_file(output_dir: str | None = None) -> str:
    out_dir = Path(
        output_dir or os.getenv("SBOM_OUTPUT_DIR", ROOT / "artifacts" / "sbom")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "enclave_sbom.cdx.json"
    source_commit = os.getenv("ENCLAVE_SOURCE_COMMIT", "unknown")
    release_id = os.getenv("ENCLAVE_RELEASE_ID", source_commit)
    components = sorted(
        _python_components() + _npm_components() + _image_components(),
        key=lambda item: item["bom-ref"],
    )
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'enclave:{release_id}:{source_commit}')}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": [
                {"vendor": "Enclave", "name": "generate_sbom.py", "version": "3.0"}
            ],
            "component": {
                "type": "application",
                "name": "Enclave",
                "version": release_id,
            },
            "properties": [
                {"name": "enclave:source_commit", "value": source_commit},
                {"name": "enclave:python_lock_sha256", "value": _sha256(PYTHON_LOCK)},
                {"name": "enclave:npm_lock_sha256", "value": _sha256(NPM_LOCK)},
            ],
        },
        "components": components,
    }
    output.write_text(json.dumps(sbom, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "NOTICE").write_text(
        "Enclave third-party inventory is recorded in enclave_sbom.cdx.json.\n"
        "PyMuPDF remains under the time-bounded P1-LIC-001 legal exception.\n"
        "Model weights and external sidecar redistribution require separate legal review.\n",
        encoding="utf-8",
    )
    return str(output)


if __name__ == "__main__":
    print(generate_sbom_file())
