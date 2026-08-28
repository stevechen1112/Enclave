"""Observed host hardware inventory for P5 profile qualification."""

from __future__ import annotations

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
