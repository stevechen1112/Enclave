"""Observed host hardware inventory for P5 profile qualification."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def detect_hardware(path: Path | None = None) -> dict[str, int | float]:
    import psutil

    disk = shutil.disk_usage(path or Path.cwd())
    gpu_vram_gb = 0.0
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            values = [
                float(line.strip()) / 1000
                for line in result.stdout.splitlines()
                if line.strip()
            ]
            gpu_vram_gb = max(values, default=0.0)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return {
        "cpu_cores": int(os.cpu_count() or 0),
        "ram_gb": round(psutil.virtual_memory().total / 1_000_000_000, 3),
        "disk_gb": round(disk.total / 1_000_000_000, 3),
        "gpu_vram_gb": round(gpu_vram_gb, 3),
    }


def hardware_shortfalls(
    observed: dict[str, Any], required: dict[str, Any]
) -> list[str]:
    shortfalls = []
    for field in ("cpu_cores", "ram_gb", "disk_gb", "gpu_vram_gb"):
        actual = float(observed.get(field, 0) or 0)
        minimum = float(required.get(field, 0) or 0)
        if actual < minimum:
            shortfalls.append(f"{field}: observed {actual:g}, requires {minimum:g}")
    return shortfalls


def co_resident_enclave_projects(target_project: str) -> list[str]:
    """Return other running Enclave Compose projects on the Docker host."""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if not target_project or any(char not in allowed for char in target_project):
        raise ValueError("Compose project name contains unsupported characters")
    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "--format",
                '{{.Label "com.docker.compose.project"}}\t{{.Names}}\t{{.Image}}',
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"docker-inspection-unavailable:{type(exc).__name__}"]
    if result.returncode != 0:
        return ["docker-inspection-unavailable"]
    projects = set()
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        project, name, image = (part.strip() for part in parts)
        if not project or project == target_project:
            continue
        if name.casefold().startswith("enclave") or "enclave" in image.casefold():
            projects.add(project)
    return sorted(projects)


def compose_container_identity(container: str, target_project: str) -> dict[str, Any]:
    """Inspect one running container and prove its Compose project binding."""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    for value, name in ((container, "container"), (target_project, "Compose project")):
        if not value or any(char not in allowed for char in value):
            raise ValueError(f"{name} contains unsupported characters")
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                container,
                "--format",
                '{{json .Config.Labels}}\t{{json .State}}\t{{json .Image}}',
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Docker container inspection failed") from exc
    if result.returncode != 0:
        raise ValueError("Docker container inspection failed")
    try:
        labels_raw, state_raw, image_raw = result.stdout.strip().split("\t", 2)
        labels = json.loads(labels_raw)
        state = json.loads(state_raw)
        image_id = json.loads(image_raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Docker container inspection returned invalid JSON") from exc
    project = str((labels or {}).get("com.docker.compose.project") or "")
    service = str((labels or {}).get("com.docker.compose.service") or "")
    running = bool((state or {}).get("Running"))
    if project != target_project or not service or not running:
        raise ValueError(
            f"container is not a running member of Compose project {target_project}"
        )
    return {
        "container": container,
        "compose_project": project,
        "compose_service": service,
        "running": running,
        "image_id": str(image_id or ""),
    }
