"""C2/C3 — provision a live PipesHub BookStack connector against the ACL fixture.

Creates (or reuses) a BookStack connector instance, writes API_TOKEN credentials,
enables it, and triggers a full resync. Produces
artifacts/pipeshub_bookstack_connector_last_run.json for CV-PH-02 / CV-PH-03.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "artifacts" / "pipeshub_bookstack_connector_last_run.json"

PIPESHUB = os.getenv("PIPESHUB_BASE_URL", "http://localhost:8012").rstrip("/")
# Host-side URL (for local verification); PipesHub container must use the
# Docker-DNS name because the two compose projects are on different networks
# until `docker network connect pipeshub-ai_network bookstack` is applied.
BOOKSTACK = os.getenv("BOOKSTACK_URL", "http://localhost:8090").rstrip("/")
BOOKSTACK_INTERNAL = os.getenv("BOOKSTACK_INTERNAL_URL", "http://bookstack").rstrip("/")
TOKEN_ID = os.getenv("BOOKSTACK_TOKEN_ID", "")
TOKEN_SECRET = os.getenv("BOOKSTACK_TOKEN_SECRET", "")
INSTANCE_NAME = os.getenv("PIPESHUB_BOOKSTACK_INSTANCE", "enclave-bookstack-acl")


async def _jwt() -> str:
    from app.gateway.token_provider import build_pipeshub_token_provider
    return await build_pipeshub_token_provider().get_token()


async def main() -> int:
    if not (TOKEN_ID and TOKEN_SECRET):
        print("BOOKSTACK_TOKEN_ID / BOOKSTACK_TOKEN_SECRET must be set")
        return 1

    jwt = await _jwt()
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    result: dict = {
        "gate": "C2-C3-bookstack-connector",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "bookstack_url": BOOKSTACK,
        "bookstack_internal_url": BOOKSTACK_INTERNAL,
        "instance_name": INSTANCE_NAME,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        # 1) Confirm BookStack is in the registry
        reg = await client.get(f"{PIPESHUB}/api/v1/connectors/registry", headers=headers)
        result["registry_status"] = reg.status_code
        names = []
        if reg.status_code == 200:
            body = reg.json()
            items = body.get("connectors") or body.get("data") or body
            if isinstance(items, list):
                names = [
                    (i.get("type") or i.get("name") or i.get("appName") or "")
                    for i in items if isinstance(i, dict)
                ]
            elif isinstance(items, dict):
                names = list(items.keys())
        result["registry_names_sample"] = names[:30]
        bookstack_type = next(
            (n for n in names if "bookstack" in n.lower() or n.upper() == "BOOKSTACK"),
            "BOOKSTACK",
        )
        result["connector_type"] = bookstack_type
        print(f"registry ok; using type={bookstack_type}")

        # 2) Reuse existing instance if present
        listing = await client.get(f"{PIPESHUB}/api/v1/connectors", headers=headers)
        existing_id = None
        if listing.status_code == 200:
            for c in (listing.json().get("connectors") or []):
                if c.get("name") == INSTANCE_NAME or c.get("instanceName") == INSTANCE_NAME:
                    existing_id = (
                        c.get("_key")
                        or c.get("connectorId")
                        or c.get("id")
                        or c.get("_id")
                    )
                    break
        result["existing_id"] = existing_id

        if existing_id:
            connector_id = existing_id
            print(f"reusing connector {connector_id}")
        else:
            create = await client.post(
                f"{PIPESHUB}/api/v1/connectors",
                headers=headers,
                json={
                    "connectorType": bookstack_type,
                    "instanceName": INSTANCE_NAME,
                    "scope": "team",
                    "authType": "API_TOKEN",
                    "config": {
                        "auth": {
                            "base_url": BOOKSTACK_INTERNAL + "/",
                            "token_id": TOKEN_ID,
                            "token_secret": TOKEN_SECRET,
                        }
                    },
                    "baseUrl": BOOKSTACK_INTERNAL + "/",
                },
            )
            result["create_status"] = create.status_code
            result["create_body"] = create.json() if create.headers.get("content-type", "").startswith("application/json") else create.text[:500]
            print(f"create: {create.status_code} {create.text[:300]}")
            if create.status_code not in (200, 201):
                OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                return 1
            data = create.json()
            conn = data.get("connector") or data.get("data") or {}
            connector_id = (
                data.get("id")
                or data.get("connectorId")
                or conn.get("connectorId")
                or conn.get("id")
            )
            if not connector_id:
                print("create succeeded but no connector id in response")
                OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                return 1

        result["connector_id"] = connector_id

        # 3) Ensure auth config is written (idempotent PUT)
        auth_put = await client.put(
            f"{PIPESHUB}/api/v1/connectors/{connector_id}/config/auth",
            headers=headers,
            json={
                "auth": {
                    "base_url": BOOKSTACK_INTERNAL + "/",
                    "token_id": TOKEN_ID,
                    "token_secret": TOKEN_SECRET,
                },
                "baseUrl": BOOKSTACK_INTERNAL + "/",
            },
        )
        result["auth_put_status"] = auth_put.status_code
        result["auth_put_body"] = auth_put.text[:300]
        print(f"auth config: {auth_put.status_code}")

        # 4) Enable sync (toggle type=sync also kicks off the first sync)
        toggle = await client.post(
            f"{PIPESHUB}/api/v1/connectors/{connector_id}/toggle",
            headers=headers,
            json={"type": "sync", "fullSync": True},
        )
        result["toggle_status"] = toggle.status_code
        result["toggle_body"] = toggle.text[:500]
        print(f"toggle: {toggle.status_code} {toggle.text[:300]}")

        # 5) Explicit resync as a belt-and-braces step
        resync = await client.post(
            f"{PIPESHUB}/api/v1/connectors/{connector_id}/resync",
            headers=headers,
            json={"fullSync": True},
        )
        result["resync_status"] = resync.status_code
        result["resync_body"] = resync.text[:500]
        print(f"resync: {resync.status_code} {resync.text[:300]}")

        # 6) Poll records briefly
        records_count = 0
        for attempt in range(12):
            await asyncio.sleep(5)
            rec = await client.get(
                f"{PIPESHUB}/api/v1/connectors/{connector_id}/records",
                headers=headers,
                params={"limit": 50},
            )
            if rec.status_code == 200:
                body = rec.json()
                items = body.get("records") or body.get("data") or body.get("items") or []
                if isinstance(items, list):
                    records_count = len(items)
                elif isinstance(body.get("pagination"), dict):
                    records_count = int(body["pagination"].get("totalCount") or 0)
            print(f"  poll[{attempt}] records_status={rec.status_code} count≈{records_count}")
            if records_count > 0:
                break
        result["records_count"] = records_count
        result["status"] = "PASS" if records_count > 0 else "PARTIAL"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {OUT} status={result['status']}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
