"""
Chaos: sidecar down must not break Enclave core search path.
Uses respx to simulate provider failures; writes artifacts/chaos_sidecar_down_last_run.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import respx
from httpx import Response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "chaos_sidecar_down_last_run.json"


async def _run() -> dict:
    os.environ["RAGFLOW_ENABLED"] = "true"
    os.environ["PIPESHUB_ENABLED"] = "true"
    os.environ["WEKNORA_ENABLED"] = "true"
    os.environ["RAGFLOW_BASE_URL"] = "http://ragflow-chaos:9380"
    os.environ["PIPESHUB_BASE_URL"] = "http://pipeshub-chaos:3000"
    os.environ["WEKNORA_BASE_URL"] = "http://weknora-chaos:8080"

    from app.gateway.adapter_factory import build_gateway_adapters, build_projection_adapters
    from app.gateway.router import GatewayRouter
    from app.gateway.contracts import SearchDomain
    from app.core.authorization import AuthorizationContext
    from app.gateway.adapters.enclave import EnclaveCanonicalAdapter

    with respx.mock(assert_all_called=False) as router_mock:
        router_mock.get(url__regex=r"http://ragflow-chaos.*").mock(side_effect=Exception("down"))
        router_mock.get(url__regex=r"http://pipeshub-chaos.*").mock(return_value=Response(503))
        router_mock.get(url__regex=r"http://weknora-chaos.*").mock(return_value=Response(503))
        router_mock.post(url__regex=r"http://.*").mock(return_value=Response(503))
        router_mock.delete(url__regex=r"http://.*").mock(return_value=Response(503))

        gw = build_gateway_adapters()
        proj = build_projection_adapters()
        assert "document" in gw
        assert "ragflow" in proj or "enclave" in proj

        # Core document path still registered
        router = GatewayRouter()
        router.register_adapter("document", EnclaveCanonicalAdapter())
        # Sidecar adapters may error; document-only search must return without raising
        authz = AuthorizationContext(
            tenant_id=uuid.uuid4(),
            subject_id=uuid.uuid4(),
            role_ids=["employee"],
            policy_revision=1,
        )
        resp = await router.search(authz=authz, query="chaos", domain=SearchDomain.DOCUMENT, top_k=5)

        # Projection reconcile fail-closed
        rag = proj.get("ragflow")
        reconcile = {"converged": True}
        if rag:
            reconcile = await rag.reconcile("document", str(uuid.uuid4()), 1)

        return {
            "gateway_keys": list(gw.keys()),
            "projection_keys": list(proj.keys()),
            "core_search_status": resp.status,
            "core_search_survived": True,
            "sidecar_reconcile_converged": reconcile.get("converged"),
            "passed": (
                "document" in gw
                and "enclave" in proj
                and resp.status in ("success", "partial", "error")
                and reconcile.get("converged") is False
            ),
        }


def main() -> int:
    try:
        checks = asyncio.run(_run())
        status = "PASS" if checks.get("passed") else "FAIL"
        error = None
    except Exception as exc:
        checks = {}
        status = "ERROR"
        error = str(exc)[:500]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "error": error,
        "checks": checks,
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
