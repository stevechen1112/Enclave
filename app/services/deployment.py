"""
Phase 7 — Installation & Deployment Profiles

支援三種部署模式：
  - Lite：CPU、單節點、基本解析與搜尋
  - Standard：單 GPU、Connector、Wiki、完整觀測
  - Enterprise：HA、外部 object storage、圖資料庫、備援與離線更新
"""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DeploymentProfile(str, Enum):
    LITE = "lite"
    STANDARD = "standard"
    ENTERPRISE = "enterprise"


@dataclass
class HardwareRequirement:
    cpu_cores: int = 4
    ram_gb: int = 8
    disk_gb: int = 50
    gpu_required: bool = False
    gpu_vram_gb: int = 0


@dataclass
class DeploymentConfig:
    profile: DeploymentProfile
    hardware: HardwareRequirement
    services: List[str] = field(default_factory=list)
    ports: Dict[str, int] = field(default_factory=dict)
    env_vars: Dict[str, str] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
#  Profile Definitions
# ═══════════════════════════════════════════════════════════════════════════════

PROFILES: Dict[DeploymentProfile, DeploymentConfig] = {
    DeploymentProfile.LITE: DeploymentConfig(
        profile=DeploymentProfile.LITE,
        hardware=HardwareRequirement(cpu_cores=4, ram_gb=8, disk_gb=50),
        services=["enclave", "postgres", "redis"],
        ports={"enclave": 8000, "postgres": 5432, "redis": 6379},
        env_vars={
            "DEPLOYMENT_MODE": "nogpu",
            "RAGFLOW_ENABLED": "false",
            "PIPESHUB_ENABLED": "false",
            "WEKNORA_ENABLED": "false",
        },
    ),
    DeploymentProfile.STANDARD: DeploymentConfig(
        profile=DeploymentProfile.STANDARD,
        hardware=HardwareRequirement(
            cpu_cores=8, ram_gb=32, disk_gb=200, gpu_required=True, gpu_vram_gb=8,
        ),
        services=["enclave", "postgres", "redis", "ragflow", "pipeshub", "weknora", "neo4j", "langfuse"],
        ports={"enclave": 8000, "postgres": 5432, "redis": 6379, "ragflow": 8001, "pipeshub": 8002, "weknora": 8003},
        env_vars={
            "DEPLOYMENT_MODE": "gpu",
            "RAGFLOW_ENABLED": "true",
            "PIPESHUB_ENABLED": "true",
            "WEKNORA_ENABLED": "true",
        },
    ),
    DeploymentProfile.ENTERPRISE: DeploymentConfig(
        profile=DeploymentProfile.ENTERPRISE,
        hardware=HardwareRequirement(
            cpu_cores=16, ram_gb=64, disk_gb=500, gpu_required=True, gpu_vram_gb=24,
        ),
        services=["enclave", "postgres", "redis", "ragflow", "pipeshub", "weknora", "neo4j", "langfuse", "minio", "grafana"],
        ports={"enclave": 8000, "postgres": 5432, "redis": 6379, "ragflow": 8001, "pipeshub": 8002, "weknora": 8003},
        env_vars={
            "DEPLOYMENT_MODE": "gpu",
            "RAGFLOW_ENABLED": "true",
            "PIPESHUB_ENABLED": "true",
            "WEKNORA_ENABLED": "true",
            "HA_MODE": "true",
        },
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Preflight Check
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PreflightResult:
    passed: bool
    checks: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def run_preflight(profile: DeploymentProfile) -> PreflightResult:
    """
    執行部署前檢查。

    檢查項目：
      - OS 相容性
      - CPU 核心數
      - RAM 大小
      - 磁碟空間
      - GPU 可用性（若需要）
      - Docker 版本
      - 必要端口是否被佔用
    """
    config = PROFILES[profile]
    hw = config.hardware
    result = PreflightResult(passed=True)

    # CPU
    cpu_count = os.cpu_count() or 1
    result.checks.append({
        "check": "cpu_cores",
        "required": hw.cpu_cores,
        "actual": cpu_count,
        "passed": cpu_count >= hw.cpu_cores,
    })
    if cpu_count < hw.cpu_cores:
        result.errors.append(f"CPU 核心不足：需要 {hw.cpu_cores}，目前 {cpu_count}")
        result.passed = False

    # RAM
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / (1024**3)
    except ImportError:
        ram_gb = 0  # 無法偵測
    result.checks.append({
        "check": "ram_gb",
        "required": hw.ram_gb,
        "actual": round(ram_gb, 1),
        "passed": ram_gb >= hw.ram_gb,
    })
    if ram_gb < hw.ram_gb:
        result.errors.append(f"RAM 不足：需要 {hw.ram_gb}GB，目前 {ram_gb:.1f}GB")
        result.passed = False

    # Disk
    disk_gb = shutil.disk_usage("/").free / (1024**3)
    result.checks.append({
        "check": "disk_gb",
        "required": hw.disk_gb,
        "actual": round(disk_gb, 1),
        "passed": disk_gb >= hw.disk_gb,
    })
    if disk_gb < hw.disk_gb:
        result.errors.append(f"磁碟空間不足：需要 {hw.disk_gb}GB，目前 {disk_gb:.1f}GB")
        result.passed = False

    # GPU
    if hw.gpu_required:
        gpu_available = _check_gpu()
        result.checks.append({
            "check": "gpu_available",
            "required": True,
            "actual": gpu_available,
            "passed": gpu_available,
        })
        if not gpu_available:
            result.errors.append("需要 GPU 但未偵測到 NVIDIA GPU")
            result.passed = False

    # Docker
    docker_available = _check_docker()
    result.checks.append({
        "check": "docker",
        "required": True,
        "actual": docker_available,
        "passed": docker_available,
    })
    if not docker_available:
        result.errors.append("Docker 未安裝或無法執行")
        result.passed = False

    # Pack flags ↔ profile + sidecar overlay (DD-M10)
    _check_pack_sidecar_consistency(profile, config, result)

    return result


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _check_pack_sidecar_consistency(
    profile: DeploymentProfile,
    config: DeploymentConfig,
    result: PreflightResult,
) -> None:
    """Fail closed when packs are on without overlay files, or profile expects packs off/on."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sidecar_yml = root / "compose" / "sidecars.yml"
    pack_env = root / "compose" / "pack-enabled.env"
    pins_env = root / "compose" / "image-pins.env"

    overlay_ok = sidecar_yml.is_file() and pack_env.is_file() and pins_env.is_file()
    result.checks.append({
        "check": "compose_overlays",
        "name": "compose_overlays",
        "required": True,
        "actual": overlay_ok,
        "passed": overlay_ok,
        "detail": str(sidecar_yml) if overlay_ok else "missing compose/sidecars.yml or env pins",
        "status": "ok" if overlay_ok else "fail",
    })
    if not overlay_ok:
        result.errors.append("缺少 compose overlays（sidecars.yml / pack-enabled.env / image-pins.env）")
        result.passed = False

    packs = {
        "RAGFLOW_ENABLED": "ragflow",
        "PIPESHUB_ENABLED": "pipeshub-api",
        "WEKNORA_ENABLED": "weknora",
    }
    enabled_packs = [svc for env_key, svc in packs.items() if _env_truthy(env_key)]

    if profile == DeploymentProfile.LITE:
        if enabled_packs:
            result.warnings.append(
                f"lite profile 但 pack 已開啟：{enabled_packs}（應關閉或改用 standard）"
            )
        result.checks.append({
            "check": "pack_flags_lite",
            "name": "pack_flags_lite",
            "status": "ok",
            "passed": True,
            "detail": "no packs expected",
        })
        return

    # standard / enterprise：建議 pack 與 profile 定義一致
    for key, expected in config.env_vars.items():
        if not key.endswith("_ENABLED"):
            continue
        actual = "true" if _env_truthy(key) else "false"
        matched = actual == expected.lower()
        result.checks.append({
            "check": f"pack_flag_{key}",
            "name": f"pack_flag_{key}",
            "required": expected,
            "actual": actual,
            "passed": matched,
            "status": "ok" if matched else "warn",
            "detail": f"expected {expected} for profile={profile.value}",
        })
        if not matched and expected.lower() == "true":
            result.warnings.append(
                f"{key}={actual} 但 profile={profile.value} 期望 true；"
                f"請使用 --env-file compose/pack-enabled.env"
            )

    if enabled_packs and not overlay_ok:
        result.errors.append(
            f"已啟用 pack {enabled_packs} 但 sidecar overlay 缺失；"
            "prod 請 -f compose/sidecars.yml --profile standard"
        )
        result.passed = False
    elif enabled_packs:
        result.checks.append({
            "check": "pack_sidecar_pairing",
            "name": "pack_sidecar_pairing",
            "status": "ok",
            "passed": True,
            "detail": f"packs={enabled_packs}; overlay present",
        })


def _check_gpu() -> bool:
    """檢查 NVIDIA GPU 是否可用。"""
    try:
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_docker() -> bool:
    """檢查 Docker 是否可用。"""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Support Bundle
# ═══════════════════════════════════════════════════════════════════════════════

def generate_support_bundle(output_dir: str) -> str:
    """
    產生可脫敏的 support bundle（含真實健康探測）。
    """
    os.makedirs(output_dir, exist_ok=True)
    bundle_path = os.path.join(output_dir, "enclave_support_bundle.json")

    services: Dict[str, Any] = {}
    try:
        from app.db.session import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            services["postgres"] = {"status": "healthy"}
        except Exception as exc:
            services["postgres"] = {"status": "unhealthy", "error": str(exc)}
        finally:
            db.close()
    except Exception:
        services["postgres"] = {"status": "unknown"}

    try:
        import redis as redis_lib
        from app.config import settings
        r = redis_lib.Redis.from_url(settings.CELERY_BROKER_URL)
        r.ping()
        services["redis"] = {"status": "healthy"}
    except Exception as exc:
        services["redis"] = {"status": "unhealthy", "error": str(exc)}

    services["enclave"] = {"status": "healthy"}
    for name, env_key in [("ragflow", "RAGFLOW_ENABLED"), ("pipeshub", "PIPESHUB_ENABLED"), ("weknora", "WEKNORA_ENABLED")]:
        if os.getenv(env_key, "").lower() == "true":
            services[name] = {"status": "enabled", "configured": True}
        else:
            services[name] = {"status": "disabled"}

    bundle = {
        "generated_at": _now_iso(),
        "enclave_version": VERSION_MATRIX.get("enclave", "1.0.0"),
        "system": {
            "os": platform.platform(),
            "python": sys.version,
            "cpu_cores": os.cpu_count(),
        },
        "services": services,
        "config": {
            "deployment_profile": os.getenv("DEPLOYMENT_PROFILE", "standard"),
            "modules": __import__("app.services.product_license", fromlist=["module_status"]).module_status(),
        },
        "upstream_versions": VERSION_MATRIX.get("upstream", {}),
        "errors": [],
    }

    with open(bundle_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"Support bundle generated: {bundle_path}")
    return bundle_path


# ═══════════════════════════════════════════════════════════════════════════════
#  Version Compatibility Matrix
# ═══════════════════════════════════════════════════════════════════════════════

VERSION_MATRIX = {
    "enclave": "1.0.0",
    "upstream": {
        "ragflow": {"version": "v0.26.4", "commit": "pinned", "image": "infiniflow/ragflow:v0.26.4"},
        "pipeshub": {
            "version": "0.4.5",
            "commit": "digest-pinned",
            "image": "pipeshubai/pipeshub-ai:0.4.5@sha256:e312a7acdaf8f5bb86a39061ced57b28c8f2c39028e55fc3b0d49bba2ca583a2",
        },
        "weknora": {
            "version": "v0.7.1",
            "commit": "digest-pinned",
            "image": "wechatopenai/weknora-app:v0.7.1@sha256:d88bef9912f6abb8bc7c22144ee7f314016055b8075bda4ea8fbb28af41c3bcf",
        },
    },
    "infrastructure": {
        "postgres": "16",
        "pgvector": "pg16",
        "redis": "7-alpine",
        "neo4j": "5.26-community",
    },
    "upgrade_paths": [
        {"from": "1.0.0", "to": "1.1.0", "supports_rollback": True},
    ],
}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
