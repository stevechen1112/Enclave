#!/usr/bin/env python3
"""Seed and prove one genuinely grounded synthetic P5 knowledge document."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


def _first_token(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value:
        raise ValueError("credential pool must be a non-empty JSON list")
    token = value[0].get("access_token") if isinstance(value[0], dict) else None
    if not token:
        raise ValueError("credential pool does not contain an access token")
    return str(token)


def _search_has_marker(payload: Any, marker: str) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(
        marker in str(row.get("content") or "")
        for row in payload.get("results", [])
        if isinstance(row, dict)
    )


def _chat_is_grounded(payload: Any) -> bool:
    return bool(
        isinstance(payload, dict)
        and str(payload.get("answer") or "").strip()
        and isinstance(payload.get("sources"), list)
        and payload["sources"]
    )


def prepare(
    *,
    client: httpx.Client,
    fixture: Path,
    marker: str,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    health = client.get("/health")
    health.raise_for_status()
    health_payload = health.json()
    release = health_payload.get("release", {}) if isinstance(health_payload, dict) else {}
    if release.get("identifiable") is not True:
        raise ValueError("staging release identity is not identifiable")
    me = client.get("/api/v1/users/me")
    me.raise_for_status()
    me_payload = me.json()
    tenant_id = str(me_payload.get("tenant_id") or "")
    if not tenant_id:
        raise ValueError("load credential is not bound to a tenant")
    with fixture.open("rb") as stream:
        upload = client.post(
            "/api/v1/knowledge/assets",
            files={"file": (fixture.name, stream, "text/markdown")},
            data={
                "title": f"P5 grounded SOP {marker}",
                "idempotency_key": f"p5-grounded:{marker}:{uuid.uuid4()}",
            },
        )
    upload.raise_for_status()
    upload_payload = upload.json()
    deadline = time.monotonic() + timeout_seconds
    search_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        search = client.post(
            "/api/v1/kb/search",
            json={"query": marker, "top_k": 5, "granularity": "chunk"},
        )
        search.raise_for_status()
        search_payload = search.json()
        if _search_has_marker(search_payload, marker):
            break
        time.sleep(poll_seconds)
    else:
        raise TimeoutError("seeded P5 fixture did not become retrievable")

    chat = client.post(
        "/api/v1/chat/chat",
        json={
            "question": f"依據 {marker}，設備復歸前壓力必須落在哪個範圍？",
            "top_k": 3,
        },
    )
    chat.raise_for_status()
    chat_payload = chat.json()
    if not _chat_is_grounded(chat_payload):
        raise ValueError("seeded P5 fixture did not produce a grounded answer")
    completed_at = datetime.now(UTC)
    return {
        "status": "PASS",
        "execution_class": "live",
        "marker": marker,
        "source_commit": str(release.get("source_commit") or ""),
        "release_id": str(release.get("release_id") or ""),
        "tenant_id": tenant_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "asset_id": str(
            upload_payload.get("id") or upload_payload.get("asset_id") or ""
        ),
        "search_results": int(search_payload.get("total_results", 0) or 0),
        "chat_sources": len(chat_payload["sources"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--marker", default="P5-SOP-RESET-042")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--confirm-isolated-staging", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_staging:
        parser.error("--confirm-isolated-staging is required")
    if args.timeout_seconds <= 0 or args.poll_seconds <= 0:
        parser.error("timeouts must be positive")
    if not args.fixture.is_file() or not args.credentials.is_file():
        parser.error("fixture and credential pool must exist")
    try:
        headers = {"Authorization": f"Bearer {_first_token(args.credentials)}"}
        with httpx.Client(
            base_url=args.base_url.rstrip("/"),
            headers=headers,
            timeout=min(args.timeout_seconds, 180),
        ) as client:
            evidence = prepare(
                client=client,
                fixture=args.fixture,
                marker=args.marker,
                timeout_seconds=args.timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
    except (OSError, TypeError, ValueError, TimeoutError, httpx.HTTPError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.chmod(args.output, 0o600)
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "search_results": evidence["search_results"],
                "chat_sources": evidence["chat_sources"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
