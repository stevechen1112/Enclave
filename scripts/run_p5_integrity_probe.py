#!/usr/bin/env python3
"""Run the post-load P5 tenant-isolation and ingestion-reconciliation probe.

This script is intentionally executed inside the isolated staging backend.  It
uses the same application database identity as the release under test and
calls the public API with a real tenant token.  It never accepts pre-computed
PASS fields.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("run timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _first_token(path: Path) -> str:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise ValueError("credential pool must be a non-empty JSON list")
    token = str(rows[0].get("access_token") or "")
    if not token:
        raise ValueError("credential pool does not contain an access token")
    return token


def _job_revision_matches(job_status: str, revision_status: str) -> bool:
    expected = {
        "ready": {"ready"},
        "review_required": {"review_required"},
        "failed": {"failed"},
        "cancelled": {"failed", "pending"},
    }
    return revision_status in expected.get(job_status, set())


def probe(
    *,
    client: httpx.Client,
    grounding: dict[str, Any],
    run_started_at: datetime,
    load_completed_at: datetime,
    reconciliation_timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.models.asset import AssetRevision, SourceAsset
    from app.models.document import Document, DocumentChunk
    from app.models.ingestion import IngestionJob
    from app.models.tenant import Tenant
    from app.services.rls import apply_rls_context

    errors: list[str] = []
    health = client.get("/health")
    health.raise_for_status()
    health_payload = health.json()
    release = health_payload.get("release", {})
    if health_payload.get("env") != "staging":
        errors.append("probe target is not staging")
    if release.get("identifiable") is not True:
        errors.append("release identity is not identifiable")
    if release.get("source_commit") != grounding.get("source_commit"):
        errors.append("grounding evidence and runtime release do not match")

    me = client.get("/api/v1/users/me")
    me.raise_for_status()
    tenant_id = uuid.UUID(str(me.json().get("tenant_id") or ""))
    if str(tenant_id) != str(grounding.get("tenant_id") or ""):
        errors.append("credential tenant does not match grounding evidence")

    asset_id = uuid.UUID(str(grounding.get("asset_id") or ""))
    document_id = uuid.UUID(str(grounding.get("document_id") or ""))
    own_asset_response = client.get(f"/api/v1/knowledge/assets/{asset_id}")
    own_asset_response.raise_for_status()
    own_asset_payload = own_asset_response.json()
    own_revision_payload = own_asset_payload.get("revision") or {}
    canonical_ok = (
        own_asset_payload.get("status") in {"active", "ready"}
        and own_revision_payload.get("ingestion_status") == "ready"
    )

    with SessionLocal() as db:
        apply_rls_context(db, tenant_id)
        asset = db.query(SourceAsset).filter(SourceAsset.id == asset_id).first()
        revision = (
            db.query(AssetRevision)
            .filter(
                AssetRevision.asset_id == asset_id,
                AssetRevision.revision == getattr(asset, "current_revision", -1),
            )
            .first()
        )
        document = db.query(Document).filter(Document.id == document_id).first()
        chunk_count = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .count()
        )
        canonical_ok = canonical_ok and bool(
            asset
            and revision
            and document
            and document.source_asset_id == asset_id
            and document.status == "completed"
            and revision.ingestion_status == "ready"
            and chunk_count > 0
        )
        other_tenant_id = (
            db.query(Tenant.id)
            .filter(Tenant.id != tenant_id, Tenant.status == "active")
            .order_by(Tenant.created_at.asc())
            .scalar()
        )
    if not canonical_ok:
        errors.append("grounded fixture canonical projection is inconsistent")
    probe_tenant_created = False
    if other_tenant_id is None:
        other_tenant_id = uuid.uuid4()
        with SessionLocal() as db:
            apply_rls_context(db, tenant_id)
            db.add(
                Tenant(
                    id=other_tenant_id,
                    name=f"P5 isolation probe {other_tenant_id}",
                    plan="free",
                    status="active",
                )
            )
            db.commit()
        probe_tenant_created = True

    foreign_asset_id = uuid.uuid4()
    direct_cross_tenant_visible = False
    foreign_http_status = 0
    foreign_created = False
    try:
        if other_tenant_id is not None:
            with SessionLocal() as db:
                apply_rls_context(db, other_tenant_id)
                db.add(
                    SourceAsset(
                        id=foreign_asset_id,
                        tenant_id=other_tenant_id,
                        asset_kind="document",
                        title=f"P5 isolation probe {foreign_asset_id}",
                        source_system="upload",
                        current_revision=0,
                        status="pending",
                    )
                )
                db.commit()
                foreign_created = True
            with SessionLocal() as db:
                apply_rls_context(db, tenant_id)
                direct_cross_tenant_visible = (
                    db.query(SourceAsset)
                    .filter(SourceAsset.id == foreign_asset_id)
                    .first()
                    is not None
                )
            foreign_response = client.get(
                f"/api/v1/knowledge/assets/{foreign_asset_id}"
            )
            foreign_http_status = foreign_response.status_code
    finally:
        if foreign_created and other_tenant_id is not None:
            with SessionLocal() as db:
                apply_rls_context(db, other_tenant_id)
                row = (
                    db.query(SourceAsset)
                    .filter(SourceAsset.id == foreign_asset_id)
                    .first()
                )
                if row is not None:
                    db.delete(row)
                    db.commit()
        if probe_tenant_created and other_tenant_id is not None:
            with SessionLocal() as db:
                apply_rls_context(db, tenant_id)
                row = db.query(Tenant).filter(Tenant.id == other_tenant_id).first()
                if row is not None:
                    db.delete(row)
                    db.commit()

    cross_tenant_leak = int(
        other_tenant_id is None
        or direct_cross_tenant_visible
        or foreign_http_status != 404
    )
    if cross_tenant_leak:
        errors.append("cross-tenant asset was not hidden by both RLS and the API")

    deadline = time.monotonic() + reconciliation_timeout_seconds
    jobs: list[tuple[IngestionJob, AssetRevision | None]] = []
    while True:
        with SessionLocal() as db:
            apply_rls_context(db, tenant_id)
            jobs = (
                db.query(IngestionJob, AssetRevision)
                .outerjoin(
                    AssetRevision,
                    (AssetRevision.tenant_id == IngestionJob.tenant_id)
                    & (AssetRevision.id == IngestionJob.asset_revision_id),
                )
                .filter(
                    IngestionJob.created_at >= run_started_at,
                    IngestionJob.created_at <= load_completed_at,
                )
                .all()
            )
        unresolved = [
            job for job, _revision in jobs if job.status in {"queued", "running"}
        ]
        if not unresolved or time.monotonic() >= deadline:
            break
        time.sleep(poll_seconds)

    mismatches = [
        str(job.id)
        for job, revision in jobs
        if revision is None
        or job.status in {"queued", "running"}
        or not _job_revision_matches(job.status, revision.ingestion_status)
    ]
    terminal_failures = [
        str(job.id)
        for job, _revision in jobs
        if job.status in {"failed", "cancelled"}
    ]
    unrecoverable_backlog = len(unresolved) + len(terminal_failures)
    if not jobs:
        errors.append("load run produced no ingestion jobs to reconcile")
    if mismatches:
        errors.append("load-run ingestion jobs did not reconcile with asset revisions")
    if terminal_failures:
        errors.append("load-run ingestion jobs ended in failed or cancelled state")

    data_corruption = 0 if canonical_ok and not mismatches else 1
    return {
        "status": "PASS" if not errors else "FAIL",
        "execution_class": "live",
        "source_commit": str(release.get("source_commit") or ""),
        "release_id": str(release.get("release_id") or ""),
        "tenant_id": str(tenant_id),
        "run_started_at": run_started_at.isoformat(),
        "load_completed_at": load_completed_at.isoformat(),
        "probe_completed_at": datetime.now(UTC).isoformat(),
        "tenant_isolation_status": "PASS" if cross_tenant_leak == 0 else "FAIL",
        "job_reconciliation_status": (
            "PASS" if jobs and not mismatches and not terminal_failures else "FAIL"
        ),
        "data_corruption": data_corruption,
        "cross_tenant_leak": cross_tenant_leak,
        "unrecoverable_backlog": int(unrecoverable_backlog),
        "observations": {
            "foreign_asset_http_status": foreign_http_status,
            "direct_cross_tenant_visible": direct_cross_tenant_visible,
            "load_run_jobs": len(jobs),
            "reconciliation_mismatches": len(mismatches),
            "terminal_job_failures": len(terminal_failures),
            "canonical_chunk_count": int(chunk_count),
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--grounding-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-started-at", required=True)
    parser.add_argument("--load-completed-at", required=True)
    parser.add_argument("--reconciliation-timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=float, default=10)
    parser.add_argument("--confirm-isolated-staging", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_staging:
        parser.error("--confirm-isolated-staging is required")
    if os.getenv("APP_ENV", "").lower() != "staging":
        parser.error("P5 integrity probe may only run in APP_ENV=staging")
    if not args.credentials.is_file() or not args.grounding_evidence.is_file():
        parser.error("credentials and grounding evidence must exist")
    if args.reconciliation_timeout_seconds <= 0 or args.poll_seconds <= 0:
        parser.error("reconciliation timeout and poll interval must be positive")
    try:
        grounding = json.loads(args.grounding_evidence.read_text(encoding="utf-8"))
        run_started_at = _parse_time(args.run_started_at)
        load_completed_at = _parse_time(args.load_completed_at)
        if load_completed_at < run_started_at:
            raise ValueError("load completion cannot precede run start")
        if load_completed_at > datetime.now(UTC):
            raise ValueError("load completion cannot be in the future")
        headers = {"Authorization": f"Bearer {_first_token(args.credentials)}"}
        with httpx.Client(
            base_url=args.base_url.rstrip("/"), headers=headers, timeout=180
        ) as client:
            result = probe(
                client=client,
                grounding=grounding,
                run_started_at=run_started_at,
                load_completed_at=load_completed_at,
                reconciliation_timeout_seconds=args.reconciliation_timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
    except (OSError, TypeError, ValueError, httpx.HTTPError) as exc:
        result = {
            "status": "FAIL",
            "execution_class": "live",
            "data_corruption": 1,
            "cross_tenant_leak": -1,
            "unrecoverable_backlog": -1,
            "tenant_isolation_status": "FAIL",
            "job_reconciliation_status": "FAIL",
            "errors": [str(exc)],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.chmod(args.output, 0o600)
    print(
        json.dumps(
            {
                "status": result["status"],
                "tenant_isolation_status": result["tenant_isolation_status"],
                "job_reconciliation_status": result["job_reconciliation_status"],
            }
        )
    )
    return 0 if result["status"] == "PASS" else 7


if __name__ == "__main__":
    raise SystemExit(main())
