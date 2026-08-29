"""Phase 7/8 — Operations: preflight, support bundle, SBOM, module status."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import require_admin, require_superuser
from app.models.user import User
from app.services.deployment import (
    VERSION_MATRIX,
    DeploymentProfile,
    generate_support_bundle,
    run_preflight,
)
from app.services.product_license import module_status
from app.services.release_metadata import get_release_metadata

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/preflight")
def preflight_check(
    current_user: Annotated[User, Depends(require_superuser)],
    profile: Annotated[str, Query()] = "standard",
) -> dict[str, Any]:
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
    current_user: Annotated[User, Depends(require_superuser)],
) -> dict[str, Any]:
    out_dir = os.getenv("SUPPORT_BUNDLE_DIR", "/tmp/enclave_support")
    path = generate_support_bundle(out_dir)
    return {"bundle_path": path}


@router.get("/version-matrix")
def version_matrix(
    current_user: Annotated[User, Depends(require_superuser)],
) -> dict[str, Any]:
    return VERSION_MATRIX


@router.get("/release")
def release_metadata(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(deps.get_db)],
) -> dict[str, Any]:
    """Return the immutable build identity visible to tenant administrators."""
    metadata = get_release_metadata()
    database_heads = sorted(
        str(value)
        for value in db.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalars()
    )
    metadata["database_schema_heads"] = database_heads
    metadata["schema_matches"] = database_heads == [metadata["schema_head"]]
    return metadata


@router.get("/modules")
def product_modules(
    current_user: Annotated[User, Depends(require_superuser)],
) -> dict[str, bool]:
    return module_status()


@router.post("/sbom")
def generate_sbom_endpoint(
    current_user: Annotated[User, Depends(require_superuser)],
) -> dict[str, Any]:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_sbom",
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "scripts", "generate_sbom.py"
        ),
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        path = mod.generate_sbom_file()
        return {"sbom_path": path}
    return {"sbom_path": "", "error": "sbom generator not found"}


class CapacityEstimateRequest(BaseModel):
    ingest_jobs_per_hour: int = Field(ge=0)
    media_hours_per_day: float = Field(ge=0)
    storage_gb: float = Field(ge=0)
    audio_hours_per_month: float = Field(default=0, ge=0)
    video_hours_per_month: float = Field(default=0, ge=0)


@router.get("/input/dashboard")
def input_operations_dashboard(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(deps.get_db)],
    profile: Annotated[str, Query()] = "standard",
) -> dict[str, Any]:
    from app.services.cost_guardrails import build_tenant_cost_report
    from app.services.input_operations import (
        admission_decision,
        input_slo_dashboard,
        onboarding_quota_template,
    )

    return {
        "tenant_id": str(current_user.tenant_id),
        "admission": admission_decision(
            db, tenant_id=current_user.tenant_id, profile=profile
        ),
        "quota_template": onboarding_quota_template(profile),
        "slo": input_slo_dashboard(
            db, tenant_id=current_user.tenant_id, profile=profile
        ),
        "cost": build_tenant_cost_report(db, current_user.tenant_id),
    }


@router.post("/input/capacity-estimate")
def input_capacity_estimate(
    payload: CapacityEstimateRequest,
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    from app.services.input_operations import estimate_capacity

    return estimate_capacity(**payload.model_dump())


@router.post("/input/reconcile")
def reconcile_input_jobs(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(deps.get_db)],
    stale_minutes: Annotated[int, Query(ge=5, le=1440)] = 60,
) -> dict[str, int]:
    from app.services.input_operations import reconcile_stale_ingestion_jobs

    result = reconcile_stale_ingestion_jobs(
        db,
        tenant_id=current_user.tenant_id,
        stale_before=datetime.now(timezone.utc) - timedelta(minutes=stale_minutes),
    )
    db.commit()
    return result
