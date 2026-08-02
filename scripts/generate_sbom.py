"""Generate CycloneDX 1.5 SBOM for Enclave release (with upstream digests)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Pin upstream images used by production profiles (update on release — no floating latest in GA)
UPSTREAM_IMAGES = {
    "ragflow": {
        "name": "infiniflow/ragflow",
        "version": os.getenv("RAGFLOW_IMAGE_TAG", "v0.26.4"),
        "purl": f"pkg:docker/infiniflow/ragflow@{os.getenv('RAGFLOW_IMAGE_TAG', 'v0.26.4')}",
        "license": "Apache-2.0",
    },
    "pipeshub": {
        "name": "pipeshubai/pipeshub-ai",
        # Prefer digest via PIPESHUB_IMAGE_DIGEST; tag fallback for local SBOM generation
        "version": os.getenv("PIPESHUB_IMAGE_TAG", "latest"),
        "purl": "pkg:docker/pipeshubai/pipeshub-ai@" + os.getenv("PIPESHUB_IMAGE_TAG", "latest"),
        "license": "Apache-2.0",
        "required_digest_env": "PIPESHUB_IMAGE_DIGEST",
    },
    "weknora": {
        "name": "wechatopenai/weknora-app",
        "version": os.getenv("WEKNORA_IMAGE_TAG", "latest"),
        "purl": "pkg:docker/wechatopenai/weknora-app@" + os.getenv("WEKNORA_IMAGE_TAG", "latest"),
        "license": "Apache-2.0",
        "required_digest_env": "WEKNORA_IMAGE_DIGEST",
    },
}


def _pip_components() -> List[Dict[str, Any]]:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True, text=True, timeout=60,
        )
        components = []
        for line in result.stdout.splitlines():
            if "==" in line:
                name, version = line.split("==", 1)
                components.append({
                    "type": "library",
                    "name": name,
                    "version": version,
                    "bom-ref": f"pkg:pypi/{name}@{version}",
                    "purl": f"pkg:pypi/{name}@{version}",
                })
        return components
    except Exception:
        return []


def _docker_digest(image: str, tag: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", f"{image}:{tag}", "--format", "{{index .RepoDigests 0}}"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            ref = result.stdout.strip()
            if "@" in ref:
                return ref.split("@", 1)[1]
    except Exception:
        pass
    return None


def generate_sbom_file(output_dir: str = None) -> str:
    out_dir = output_dir or os.getenv("SBOM_OUTPUT_DIR", str(
        __import__("pathlib").Path(__file__).resolve().parents[1] / "artifacts" / "sbom"
    ))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "enclave_sbom.cdx.json")

    components = _pip_components()
    missing_digests = []
    for key, meta in UPSTREAM_IMAGES.items():
        digest = os.getenv(meta.get("required_digest_env", ""), "").strip() or None
        if not digest:
            digest = _docker_digest(meta["name"], meta["version"])
        if not digest and meta["version"] == "latest":
            missing_digests.append(key)
        comp: Dict[str, Any] = {
            "type": "container",
            "name": meta["name"],
            "version": meta["version"],
            "bom-ref": meta["purl"],
            "purl": meta["purl"],
            "licenses": [{"license": {"id": meta["license"]}}],
            "properties": [{"name": "enclave:upstream", "value": key}],
        }
        if digest:
            comp["hashes"] = [{"alg": "SHA-256", "content": digest.replace("sha256:", "")}]
            comp["properties"].append({"name": "enclave:image_digest", "value": digest})
        components.append(comp)

    sbom: Dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": [{"vendor": "Enclave", "name": "generate_sbom.py", "version": "2.1"}],
            "component": {
                "type": "application",
                "name": "Enclave",
                "version": os.getenv("ENCLAVE_VERSION", "1.0.0"),
            },
            "properties": [
                {"name": "enclave:sbom_warnings", "value": ",".join(missing_digests) or "none"},
            ],
        },
        "components": components,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sbom, f, indent=2, ensure_ascii=False)

    notice = os.path.join(out_dir, "NOTICE")
    with open(notice, "w", encoding="utf-8") as f:
        f.write("Enclave NOTICE — third-party components\n")
        f.write("======================================\n")
        f.write("Primary license: Apache-2.0 (see /LICENSE).\n")
        f.write("SBOM: enclave_sbom.cdx.json (CycloneDX 1.5).\n")
        f.write("GA gate: upstream images must have locked digests (no floating latest).\n\n")
        f.write("Upstream sidecars:\n")
        for key, meta in UPSTREAM_IMAGES.items():
            f.write(f"- {key}: {meta['name']}:{meta['version']} ({meta['license']})\n")
        f.write("\nPython packages (from pip freeze):\n")
        for comp in components:
            if comp.get("type") == "library":
                f.write(f"- {comp['name']}=={comp['version']}\n")
        if missing_digests:
            f.write(f"\nWARNING: missing digests for: {', '.join(missing_digests)}\n")
            f.write("Set PIPESHUB_IMAGE_DIGEST / WEKNORA_IMAGE_DIGEST before GA release.\n")
        f.write(
            "\nLegal review of model weights / OCR / VLM redistribution is a human GA gate.\n"
        )

    # Fail hard for GA-style generation when digests missing and STRICT_SBOM=true
    if missing_digests and os.getenv("STRICT_SBOM", "").lower() == "true":
        raise SystemExit(f"STRICT_SBOM: missing digests for {missing_digests}")
    return path


if __name__ == "__main__":
    print(generate_sbom_file())
