#!/usr/bin/env python3
"""Run a release-bound, non-destructive production concurrency probe.

This is an operational smoke, not P5 capacity certification.  It uses one
synthetic/internal tenant credential and performs only health, identity, asset
list, and deliberately non-matching search requests.  No token or credential
is written to evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

_SCENARIOS = ("health", "identity", "asset_list", "empty_search")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(percentile * len(ordered) + 0.999) - 1))
    return round(ordered[index], 2)


def _one_request(
    client: httpx.Client,
    *,
    scenario: str,
    headers: dict[str, str],
    marker: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        if scenario == "health":
            response = client.get("/health")
        elif scenario == "identity":
            response = client.get("/api/v1/users/me", headers=headers)
        elif scenario == "asset_list":
            response = client.get(
                "/api/v1/knowledge/assets", headers=headers, params={"limit": 5}
            )
        elif scenario == "empty_search":
            response = client.post(
                "/api/v1/gateway/search",
                headers=headers,
                json={"query": marker, "top_k": 3, "domain": "hybrid"},
            )
        else:
            raise ValueError(f"unknown scenario: {scenario}")
        return {
            "scenario": scenario,
            "status_code": response.status_code,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "error": None,
        }
    except Exception as exc:  # evidence must include transport failures
        return {
            "scenario": scenario,
            "status_code": 0,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "error": type(exc).__name__,
        }


def run_probe(
    *,
    client: httpx.Client,
    username: str,
    password: str,
    expected_tenant_id: str,
    expected_release_id: str,
    concurrency: int,
    request_count: int,
) -> dict[str, Any]:
    if not 1 <= concurrency <= 50:
        raise ValueError("concurrency must be between 1 and 50")
    if not concurrency <= request_count <= 200:
        raise ValueError("request_count must be between concurrency and 200")
    started_at = datetime.now(UTC)
    health = client.get("/health")
    health.raise_for_status()
    release = (health.json().get("release") or {})
    if release.get("release_id") != expected_release_id:
        raise RuntimeError("public release does not match the explicitly expected release")
    login = client.post(
        "/api/v1/auth/login/access-token",
        data={"username": username, "password": password},
    )
    login.raise_for_status()
    token = str(login.json().get("access_token") or "")
    if not token:
        raise RuntimeError("login returned no access token")
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/users/me", headers=headers)
    me.raise_for_status()
    if str(me.json().get("tenant_id") or "") != expected_tenant_id:
        raise RuntimeError("credential tenant does not match the explicit probe tenant")

    marker = f"PRA-PROBE-NO-HIT-{uuid.uuid4().hex}"
    observations: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                _one_request,
                client,
                scenario=_SCENARIOS[index % len(_SCENARIOS)],
                headers=headers,
                marker=marker,
            )
            for index in range(request_count)
        ]
        for future in as_completed(futures):
            observations.append(future.result())

    latencies = [float(row["latency_ms"]) for row in observations]
    failures = [row for row in observations if row["status_code"] != 200]
    scenarios = {}
    for scenario in _SCENARIOS:
        rows = [row for row in observations if row["scenario"] == scenario]
        scenarios[scenario] = {
            "requests": len(rows),
            "failures": sum(row["status_code"] != 200 for row in rows),
            "p95_ms": _percentile(
                [float(row["latency_ms"]) for row in rows], 0.95
            ),
            "status_codes": sorted({int(row["status_code"]) for row in rows}),
        }
    completed_at = datetime.now(UTC)
    return {
        "schema_version": "pra-bounded-probe/v1",
        "status": "PASS" if not failures else "FAIL",
        "execution_class": "production_non_destructive_smoke",
        "formal_capacity_evidence": False,
        "release_id": expected_release_id,
        "source_commit": str(release.get("source_commit") or ""),
        "tenant_ref_sha256": hashlib.sha256(expected_tenant_id.encode()).hexdigest(),
        "concurrency": concurrency,
        "request_count": request_count,
        "failure_count": len(failures),
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
            "max": round(max(latencies, default=0.0), 2),
        },
        "scenarios": scenarios,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_ms": round((completed_at - started_at).total_seconds() * 1000),
        "errors": [row["error"] for row in failures if row["error"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://kachu.tw")
    parser.add_argument("--expected-tenant-id", required=True)
    parser.add_argument("--expected-release-id", required=True)
    parser.add_argument("--concurrency", type=int, default=40)
    parser.add_argument("--request-count", type=int, default=80)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    username = os.environ.get("PRA_E2E_USERNAME") or os.environ.get(
        "FIRST_SUPERUSER_EMAIL", ""
    )
    password = os.environ.get("PRA_E2E_PASSWORD") or os.environ.get(
        "FIRST_SUPERUSER_PASSWORD", ""
    )
    if not username or not password:
        parser.error("PRA_E2E_USERNAME and PRA_E2E_PASSWORD are required")
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60) as client:
        result = run_probe(
            client=client,
            username=username,
            password=password,
            expected_tenant_id=args.expected_tenant_id,
            expected_release_id=args.expected_release_id,
            concurrency=args.concurrency,
            request_count=args.request_count,
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
