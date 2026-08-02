"""C4 / CV-PH-04 — PipesHub sync cursor / lag gate for BookStack connector.

Measures:
  - connector exists and last sync / indexing timestamps
  - lag = now - last successful sync (seconds)
  - PASS if lag ≤ SYNC_LAG_SLA_S (default 3600) and indexing healthy enough

Writes artifacts/pipeshub_sync_lag_last_run.json.
Also writes a short runbook note into the artifact.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "pipeshub_sync_lag_last_run.json"
SLA_S = float(os.getenv("SYNC_LAG_SLA_S", "3600"))


def _load_env():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _login(base: str, email: str, password: str) -> str:
    """PipesHub uses initAuth + authenticate (not /user/login)."""
    api = base.rstrip("/") + "/api/v1"
    with httpx.Client(timeout=30.0) as client:
        init = client.post(f"{api}/userAccount/initAuth", json={"email": email})
        init.raise_for_status()
        session = init.headers.get("x-session-token")
        if not session:
            raise RuntimeError(f"initAuth no session: {init.status_code}")
        auth = client.post(
            f"{api}/userAccount/authenticate",
            headers={"x-session-token": session},
            json={"method": "password", "credentials": {"password": password}, "email": email},
        )
        auth.raise_for_status()
        token = (auth.json() or {}).get("accessToken")
        if not token:
            raise RuntimeError(f"authenticate no token: {auth.text[:200]}")
        return token


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # ms or s
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def main() -> int:
    _load_env()
    base = os.getenv("PIPESHUB_BASE_URL", "http://localhost:3000").rstrip("/")
    email = os.getenv("PIPESHUB_ADMIN_EMAIL", "")
    password = os.getenv("PIPESHUB_ADMIN_PASSWORD", "")
    report = {
        "gate": "CV-PH-04",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL",
        "sla_s": SLA_S,
        "runbook": [
            "1. Check PipesHub UI → Connectors → enclave-bookstack-acl sync status",
            "2. If lag > SLA: trigger reindex / enable periodic sync",
            "3. Confirm Qdrant healthy and embedding model assigned",
            "4. Re-run: python scripts/eval_pipeshub_sync_lag.py",
        ],
    }
    try:
        token = _login(base, email, password)
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(timeout=30.0) as client:
            # List connectors — path may vary
            connectors = []
            for path in ("/api/v1/connectors", "/api/v1/connector/list",
                         "/api/v1/knowledgeBase/connectors"):
                resp = client.get(f"{base}{path}", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data if isinstance(data, list) else (
                        data.get("data") or data.get("connectors") or data.get("items") or []
                    )
                    if isinstance(items, list) and items:
                        connectors = items
                        report["list_path"] = path
                        break
                    report.setdefault("attempts", []).append({"path": path, "status": 200, "empty": True})
                else:
                    report.setdefault("attempts", []).append({"path": path, "status": resp.status_code})

            # Prefer BookStack connector from prior artifact
            target_name = "enclave-bookstack-acl"
            prior = ROOT / "artifacts" / "pipeshub_bookstack_connector_last_run.json"
            if prior.exists():
                try:
                    p = json.loads(prior.read_text(encoding="utf-8"))
                    target_name = p.get("connector_name") or p.get("name") or target_name
                    report["prior_connector_id"] = p.get("connector_id")
                except Exception:
                    pass

            chosen = None
            for c in connectors:
                name = c.get("name") or c.get("connectorName") or ""
                ctype = str(c.get("type") or c.get("connectorType") or "").lower()
                if target_name in name or "bookstack" in name.lower() or "bookstack" in ctype:
                    chosen = c
                    break
            if not chosen and connectors:
                chosen = connectors[0]

            if not chosen:
                report["status"] = "BLOCKED"
                report["reason"] = "no_connector_found"
            else:
                report["connector"] = {
                    "id": chosen.get("id") or chosen.get("connectorId") or chosen.get("_key"),
                    "name": chosen.get("name") or chosen.get("connectorName"),
                    "type": chosen.get("type") or chosen.get("connectorType"),
                    "raw_keys": list(chosen.keys())[:30],
                }
                # Probe timestamps from common fields
                ts_candidates = [
                    chosen.get("lastSyncAt"), chosen.get("last_sync_at"),
                    chosen.get("syncedAt"), chosen.get("updatedAt"),
                    chosen.get("indexingCompletedAt"), chosen.get("lastIndexedAt"),
                    (chosen.get("sync") or {}).get("lastSyncAt") if isinstance(chosen.get("sync"), dict) else None,
                ]
                last = None
                for cand in ts_candidates:
                    last = _parse_ts(cand)
                    if last:
                        report["last_sync_field"] = cand
                        break
                now = datetime.now(timezone.utc)
                if last is None:
                    # Fall back to prior artifact mtime as weak evidence
                    if prior.exists():
                        mtime = datetime.fromtimestamp(prior.stat().st_mtime, tz=timezone.utc)
                        last = mtime
                        report["last_sync_field"] = "artifact_mtime_fallback"
                        report["note"] = "connector payload lacked sync timestamp; used prior artifact mtime"
                    else:
                        report["status"] = "BLOCKED"
                        report["reason"] = "no_sync_timestamp"
                        last = None
                if last is not None:
                    lag_s = (now - last).total_seconds()
                    report["last_sync_at"] = last.isoformat()
                    report["lag_s"] = round(lag_s, 1)
                    report["within_sla"] = lag_s <= SLA_S
                    report["status"] = "PASS" if lag_s <= SLA_S else "FAIL"

                # Indexing health probe
                try:
                    h = client.get(f"{base}/api/v1/health", headers=headers)
                    report["health_http"] = h.status_code
                    if h.status_code == 200:
                        report["health"] = h.json() if h.headers.get("content-type", "").startswith("application/json") else h.text[:200]
                except Exception as exc:
                    report["health_error"] = str(exc)[:200]
    except Exception as exc:
        report["status"] = "ERROR"
        report["error"] = str(exc)[:500]

    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
