#!/usr/bin/env python3
"""Exercise the P5 tenant cost report and fail-closed query guardrail live."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.capacity_gate import load_capacity_spec


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def run_live_cost_drill(
    *,
    base_url: str,
    tenant_id: str,
    email: str,
    password: str,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = load_capacity_spec()
    transcript: dict[str, Any] = {
        "schema_version": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "tenant_id": tenant_id,
        "steps": {},
    }
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        login = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": email, "password": password},
        )
        transcript["steps"]["login"] = {"status_code": login.status_code}
        login.raise_for_status()
        token = _json(login).get("access_token")
        if not token:
            raise ValueError("login did not return an access token")
        headers = {"Authorization": f"Bearer {token}"}
        quota_url = f"/api/v1/admin/tenants/{tenant_id}/quota"
        original_response = client.get(quota_url, headers=headers)
        original_response.raise_for_status()
        original = _json(original_response)
        report_response = client.get(
            "/api/v1/analytics/cost-units",
            params={"tenant_id": tenant_id},
            headers=headers,
        )
        report_response.raise_for_status()
        modeled = _json(report_response)
        current = float(original.get("current_monthly_cost_usd", 0) or 0)
        reservation = float(spec["cost_units"]["queries_1000"]) / 1000
        temporary_limit = current + reservation / 2
        temporary = {
            "monthly_query_limit": None,
            "monthly_token_limit": None,
            "monthly_cost_limit_usd": temporary_limit,
        }
        restored = False
        blocked_response: httpx.Response | None = None
        try:
            update = client.put(quota_url, json=temporary, headers=headers)
            update.raise_for_status()
            blocked_response = client.post(
                "/api/v1/chat/chat",
                json={"question": "P5 cost guardrail live probe", "top_k": 1},
                headers=headers,
            )
        finally:
            restore = client.put(
                quota_url,
                json={
                    "monthly_query_limit": original.get("monthly_query_limit"),
                    "monthly_token_limit": original.get("monthly_token_limit"),
                    "monthly_cost_limit_usd": original.get("monthly_cost_limit_usd"),
                },
                headers=headers,
            )
            restored = restore.status_code == 200
        if blocked_response is None:
            raise ValueError("cost probe did not execute")
        blocked_payload = _json(blocked_response)
        detail = blocked_payload.get("detail", blocked_payload)
        blocked_on_cost = (
            blocked_response.status_code == 429
            and isinstance(detail, dict)
            and detail.get("axis") == "cost"
        )
        expected_units = spec["cost_units"]
        observed_rows = {
            row.get("unit"): row
            for row in modeled.get("unit_reports", [])
            if isinstance(row, dict)
        }
        unit_reports = [
            {
                "unit": unit,
                "status": (
                    "PASS"
                    if unit in observed_rows
                    and float(observed_rows[unit].get("rate_usd", -1)) == float(rate)
                    else "FAIL"
                ),
                "rate_usd": observed_rows.get(unit, {}).get("rate_usd"),
                "usage": observed_rows.get(unit, {}).get("usage"),
            }
            for unit, rate in expected_units.items()
        ]
        passed = (
            restored
            and blocked_on_cost
            and all(row["status"] == "PASS" for row in unit_reports)
        )
        transcript["steps"].update(
            {
                "cost_report": modeled,
                "temporary_limit_usd": temporary_limit,
                "blocked_probe": {
                    "status_code": blocked_response.status_code,
                    "payload": blocked_payload,
                },
                "quota_restored": restored,
            }
        )
        transcript["completed_at"] = datetime.now(UTC).isoformat()
        report = {
            "status": "PASS" if passed else "FAIL",
            "execution_class": "live",
            "overage_unbounded": not blocked_on_cost,
            "tenant_id": tenant_id,
            "started_at": transcript["started_at"],
            "completed_at": transcript["completed_at"],
            "quota_restored": restored,
            "unit_reports": unit_reports,
        }
        return report, transcript


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password-env", default="P5_ADMIN_PASSWORD")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--confirm-isolated-staging", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_staging:
        parser.error("--confirm-isolated-staging is required")
    password = os.getenv(args.password_env, "")
    if not password:
        parser.error(f"{args.password_env} must be injected")
    try:
        report, transcript = run_live_cost_drill(
            base_url=args.base_url,
            tenant_id=args.tenant_id,
            email=args.email,
            password=password,
            timeout=args.timeout_seconds,
        )
    except (ValueError, httpx.HTTPError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    transcript_path = args.output.with_suffix(".raw.json")
    transcript_path.write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report["artifact_sha256"] = _sha256(transcript_path)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 9


if __name__ == "__main__":
    raise SystemExit(main())
