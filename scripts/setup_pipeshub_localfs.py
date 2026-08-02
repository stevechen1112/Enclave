"""C2 — provision a real PipesHub LOCAL_FS connector (not nas_local lite).

Points at testdata/golden/files (or PIPESHUB_LOCALFS_PATH) via a path that the
PipesHub container can read. Prefer a docker-mounted host path.

Writes artifacts/pipeshub_localfs_connector_last_run.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "pipeshub_localfs_connector_last_run.json"
DEFAULT_HOST_PATH = ROOT / "testdata" / "golden" / "files"


def _load_env():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def login(base: str, email: str, password: str) -> str:
    api = base.rstrip("/") + "/api/v1"
    with httpx.Client(timeout=30.0) as client:
        init = client.post(f"{api}/userAccount/initAuth", json={"email": email})
        init.raise_for_status()
        session = init.headers.get("x-session-token")
        auth = client.post(
            f"{api}/userAccount/authenticate",
            headers={"x-session-token": session},
            json={"method": "password", "credentials": {"password": password}, "email": email},
        )
        auth.raise_for_status()
        return (auth.json() or {})["accessToken"]


def main() -> int:
    _load_env()
    base = os.getenv("PIPESHUB_BASE_URL", "http://localhost:8012").rstrip("/")
    email = os.getenv("PIPESHUB_ADMIN_EMAIL", "")
    password = os.getenv("PIPESHUB_ADMIN_PASSWORD", "")
    # Path as seen FROM the PipesHub container. Override if you bind-mount differently.
    container_path = os.getenv(
        "PIPESHUB_LOCALFS_CONTAINER_PATH",
        "/data/enclave-golden-files",
    )
    host_path = Path(os.getenv("PIPESHUB_LOCALFS_PATH", str(DEFAULT_HOST_PATH)))
    report = {
        "gate": "C2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL",
        "host_path": str(host_path),
        "container_path": container_path,
        "note": (
            "nas_local / Enclave lite scanner is NOT counted as PipesHub certification. "
            "This connector uses PipesHub Connectors.LOCAL_FS."
        ),
    }
    if not host_path.is_dir():
        report["reason"] = "host_path_missing"
        ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    try:
        token = login(base, email, password)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        with httpx.Client(timeout=60.0) as client:
            # Ensure container can see the path: try docker cp / mount check
            # Best-effort: copy golden files into a volume the container mounts.
            # Prefer existing mount; if missing, docker cp into pipeshub-ai container.
            try:
                import subprocess
                # Check if path exists in container
                chk = subprocess.run(
                    ["docker", "exec", "pipeshub-ai", "ls", container_path],
                    capture_output=True, text=True,
                )
                if chk.returncode != 0:
                    # Create and copy
                    subprocess.run(
                        ["docker", "exec", "pipeshub-ai", "mkdir", "-p", container_path],
                        check=False,
                    )
                    # docker cp host_path/. container:path/
                    subprocess.run(
                        ["docker", "cp", f"{host_path}/.", f"pipeshub-ai:{container_path}/"],
                        check=True,
                    )
                    report["copied_into_container"] = True
                else:
                    report["copied_into_container"] = False
                    report["container_ls_sample"] = chk.stdout.splitlines()[:10]
            except Exception as exc:
                report["container_path_error"] = str(exc)[:300]

            # Create connector instance
            body = {
                "connectorName": "LOCAL_FS",
                "name": "enclave-localfs-golden",
                "isActive": True,
                "appname": "enclave-localfs-golden",
            }
            # API shapes vary — try a few
            created = None
            for path, payload in [
                ("/api/v1/connectors", {
                    "type": "LOCAL_FS",
                    "name": "enclave-localfs-golden",
                    "config": {"basePath": container_path, "path": container_path},
                }),
                ("/api/v1/connectors", {
                    "connectorName": "LOCAL_FS",
                    "name": "enclave-localfs-golden",
                    "authType": "NONE",
                    "config": {"localPath": container_path},
                }),
            ]:
                resp = client.post(f"{base}{path}", headers=headers, json=payload)
                report.setdefault("create_attempts", []).append(
                    {"path": path, "status": resp.status_code, "body": resp.text[:300]}
                )
                if resp.status_code < 300:
                    created = resp.json()
                    break

            if not created:
                # List existing and reuse if present
                for path in ("/api/v1/connectors",):
                    resp = client.get(f"{base}{path}", headers=headers)
                    if resp.status_code == 200:
                        items = resp.json()
                        if isinstance(items, dict):
                            items = items.get("data") or items.get("connectors") or []
                        for c in items if isinstance(items, list) else []:
                            name = str(c.get("name") or "")
                            if "localfs" in name.lower() or "local_fs" in name.lower() or "LOCAL_FS" in str(c.get("type")):
                                created = c
                                report["reused_existing"] = True
                                break

            if not created:
                report["status"] = "BLOCKED"
                report["reason"] = "could_not_create_or_find_local_fs_connector"
            else:
                cid = (
                    created.get("id")
                    or created.get("connectorId")
                    or (created.get("connector") or {}).get("connectorId")
                    or created.get("_key")
                )
                report["connector"] = {
                    "id": cid,
                    "name": created.get("name") or created.get("connectorName"),
                    "raw_keys": list(created.keys())[:20] if isinstance(created, dict) else [],
                }
                # Try enable sync / reindex
                if cid:
                    for path in (
                        f"/api/v1/connectors/{cid}/sync",
                        f"/api/v1/connectors/{cid}/reindex",
                        f"/api/v1/connectors/{cid}/config",
                    ):
                        try:
                            r = client.post(f"{base}{path}", headers=headers, json={
                                "basePath": container_path, "path": container_path,
                            })
                            report.setdefault("sync_attempts", []).append(
                                {"path": path, "status": r.status_code, "body": r.text[:200]}
                            )
                        except Exception as exc:
                            report.setdefault("sync_attempts", []).append(
                                {"path": path, "error": str(exc)[:200]}
                            )
                report["status"] = "PASS" if cid else "FAIL"
                report["disclaimer"] = (
                    "PASS means a PipesHub LOCAL_FS connector record exists and sync was "
                    "attempted. Do not equate with nas_local Enclave lite scanner."
                )
    except Exception as exc:
        report["status"] = "ERROR"
        report["error"] = str(exc)[:500]

    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
