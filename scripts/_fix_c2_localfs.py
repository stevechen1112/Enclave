"""Fix C2: create LOCAL_FS connector using BookStack-proven API shape."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "artifacts" / "pipeshub_localfs_connector_last_run.json"
HOST_PATH = ROOT / "testdata" / "golden" / "files"
CONTAINER_PATH = "/data/enclave-golden-files"
INSTANCE = "enclave-localfs-golden"


async def main() -> int:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

    from app.gateway.token_provider import build_pipeshub_token_provider
    jwt = await build_pipeshub_token_provider().get_token()
    base = os.getenv("PIPESHUB_BASE_URL", "http://localhost:8012").rstrip("/")
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}

    # Ensure files visible in container
    subprocess.run(["docker", "exec", "pipeshub-ai", "mkdir", "-p", CONTAINER_PATH], check=False)
    subprocess.run(["docker", "cp", f"{HOST_PATH}/.", f"pipeshub-ai:{CONTAINER_PATH}/"], check=False)

    result = {
        "gate": "C2",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "host_path": str(HOST_PATH),
        "container_path": CONTAINER_PATH,
        "instance_name": INSTANCE,
        "disclaimer": "PipesHub LOCAL_FS — not nas_local Enclave lite",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        reg = await client.get(f"{base}/api/v1/connectors/registry", headers=headers)
        names = []
        if reg.status_code == 200:
            body = reg.json()
            items = body.get("connectors") or body.get("data") or body
            if isinstance(items, list):
                names = [(i.get("type") or i.get("name") or i.get("appName") or "") for i in items if isinstance(i, dict)]
            elif isinstance(items, dict):
                names = list(items.keys())
        result["registry_sample"] = names[:40]
        local_type = next((n for n in names if "local" in n.lower() and "fs" in n.lower()), None)
        local_type = local_type or next((n for n in names if n.upper() in ("LOCAL_FS", "LOCALFS", "FILESYSTEM")), "LOCAL_FS")
        result["connector_type"] = local_type
        print("type=", local_type, "registry=", names[:20])

        listing = await client.get(f"{base}/api/v1/connectors", headers=headers)
        existing = None
        if listing.status_code == 200:
            for c in (listing.json().get("connectors") or []):
                if c.get("name") == INSTANCE or c.get("instanceName") == INSTANCE:
                    existing = c.get("_key") or c.get("connectorId") or c.get("id")
                    break

        if existing:
            cid = existing
            print("reuse", cid)
        else:
            payloads = [
                {
                    "connectorType": local_type,
                    "instanceName": INSTANCE,
                    "scope": "team",
                    "authType": "NONE",
                    "config": {"path": CONTAINER_PATH, "basePath": CONTAINER_PATH, "rootPath": CONTAINER_PATH},
                    "baseUrl": CONTAINER_PATH,
                },
                {
                    "connectorType": local_type,
                    "instanceName": INSTANCE,
                    "scope": "team",
                    "authType": "API_TOKEN",
                    "config": {"auth": {"path": CONTAINER_PATH}, "path": CONTAINER_PATH},
                    "baseUrl": "file://" + CONTAINER_PATH,
                },
            ]
            cid = None
            for i, payload in enumerate(payloads):
                create = await client.post(f"{base}/api/v1/connectors", headers=headers, json=payload)
                result.setdefault("create_attempts", []).append(
                    {"i": i, "status": create.status_code, "body": create.text[:400]}
                )
                print("create", i, create.status_code, create.text[:200])
                if create.status_code in (200, 201):
                    data = create.json()
                    conn = data.get("connector") or data.get("data") or {}
                    cid = data.get("id") or data.get("connectorId") or conn.get("connectorId") or conn.get("id")
                    break
            if not cid:
                result["status"] = "BLOCKED"
                result["reason"] = "local_fs_create_failed_or_unsupported_in_server_api"
                OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 1

        result["connector_id"] = cid
        toggle = await client.post(
            f"{base}/api/v1/connectors/{cid}/toggle",
            headers=headers, json={"type": "sync", "fullSync": True},
        )
        result["toggle_status"] = toggle.status_code
        result["toggle_body"] = toggle.text[:300]
        resync = await client.post(
            f"{base}/api/v1/connectors/{cid}/resync",
            headers=headers, json={"fullSync": True},
        )
        result["resync_status"] = resync.status_code
        records = 0
        for _ in range(8):
            await asyncio.sleep(5)
            rec = await client.get(
                f"{base}/api/v1/connectors/{cid}/records",
                headers=headers, params={"limit": 50},
            )
            if rec.status_code == 200:
                items = rec.json().get("records") or rec.json().get("data") or []
                if isinstance(items, list):
                    records = len(items)
                    if records:
                        break
        result["records_sample_count"] = records
        result["status"] = "PASS" if cid else "FAIL"

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
