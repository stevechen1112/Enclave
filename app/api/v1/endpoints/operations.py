"""Phase 7/8 — Operations: preflight, support bundle, SBOM, module status."""
from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from app.api.deps_permissions import require_superuser
from app.models.user import User
from app.services.deployment import (
    DeploymentProfile, run_preflight, generate_support_bundle, VERSION_MATRIX,
)
from app.services.product_license import module_status

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/preflight")
def preflight_check(
    profile: str = Query("standard"),
    current_user: User = Depends(require_superuser),
) -> Dict[str, Any]:
    try:
        p = DeploymentProfile(profile)
    except ValueError:
        p = DeploymentProfile.STANDARD
    result = run_preflight(p)
    return {
        "passed": result.passed,
        "profile": profile,
        "checks": result.checks,
        "errors": result.errors,
        "warnings": result.warnings,
    }


@router.post("/support-bundle")
def create_support_bundle(
    current_user: User = Depends(require_superuser),
) -> Dict[str, Any]:
    out_dir = os.getenv("SUPPORT_BUNDLE_DIR", "/tmp/enclave_support")
    path = generate_support_bundle(out_dir)
    return {"bundle_path": path}


@router.get("/version-matrix")
def version_matrix(current_user: User = Depends(require_superuser)) -> Dict[str, Any]:
    return VERSION_MATRIX


@router.get("/modules")
def product_modules(current_user: User = Depends(require_superuser)) -> Dict[str, bool]:
    return module_status()


@router.post("/sbom")
def generate_sbom_endpoint(current_user: User = Depends(require_superuser)) -> Dict[str, Any]:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "generate_sbom",
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "generate_sbom.py"),
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        path = mod.generate_sbom_file()
        return {"sbom_path": path}
    return {"sbom_path": "", "error": "sbom generator not found"}
