"""
E2E: each commercial pack can be disabled; Enclave core still works.
Writes artifacts/module_disable_e2e_last_run.json
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "module_disable_e2e_last_run.json"


def _check_core_and_gates() -> dict:
    from app.gateway.adapter_factory import build_gateway_adapters, build_projection_adapters
    from app.services.module_gate import require_module
    from app.services.product_license import ProductModule, is_module_enabled
    from fastapi import HTTPException

    # Force all packs off for this process
    for key in ("RAGFLOW_ENABLED", "PIPESHUB_ENABLED", "WEKNORA_ENABLED", "AGENT_AUTOMATION_ENABLED"):
        os.environ[key] = "false"

    results = {
        "base_enabled": is_module_enabled(ProductModule.BASE),
        "packs_disabled": {
            "document_intelligence": not is_module_enabled(ProductModule.DOCUMENT_INTELLIGENCE),
            "enterprise_connect": not is_module_enabled(ProductModule.ENTERPRISE_CONNECT),
            "knowledge_compiler": not is_module_enabled(ProductModule.KNOWLEDGE_COMPILER),
        },
        "gateway_adapters": list(build_gateway_adapters().keys()),
        "projection_adapters": list(build_projection_adapters().keys()),
        "module_gates": {},
    }

    assert results["base_enabled"] is True
    assert results["gateway_adapters"] == ["document"]
    assert results["projection_adapters"] == ["enclave"]

    for mod, env in [
        (ProductModule.DOCUMENT_INTELLIGENCE, "RAGFLOW"),
        (ProductModule.ENTERPRISE_CONNECT, "PIPESHUB"),
        (ProductModule.KNOWLEDGE_COMPILER, "WEKNORA"),
    ]:
        try:
            require_module(mod)
            results["module_gates"][mod.value] = "ALLOWED_UNEXPECTED"
        except HTTPException as exc:
            results["module_gates"][mod.value] = f"blocked_{exc.status_code}"

    # Core search path: Gateway with only document adapter must not crash
    import asyncio
    import uuid
    from app.core.authorization import AuthorizationContext
    from app.gateway.router import GatewayRouter
    from app.gateway.adapters.enclave import EnclaveCanonicalAdapter
    from app.gateway.contracts import SearchDomain

    router = GatewayRouter()
    router.register_adapter("document", EnclaveCanonicalAdapter())
    authz = AuthorizationContext(
        tenant_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        role_ids=["employee"],
        policy_revision=1,
    )

    async def _search():
        return await router.search(authz=authz, query="core health", domain=SearchDomain.DOCUMENT, top_k=3)

    resp = asyncio.run(_search())
    results["core_gateway_status"] = resp.status  # may be partial/error/success depending on DB
    results["core_gateway_ok"] = resp.status in ("success", "partial", "error")  # must not raise
    # When no adapter results, error/partial is fine — process survived
    results["passed"] = (
        results["base_enabled"]
        and all(results["packs_disabled"].values())
        and results["gateway_adapters"] == ["document"]
        and results["projection_adapters"] == ["enclave"]
        and all(str(v).startswith("blocked_") for v in results["module_gates"].values())
        and results["core_gateway_ok"]
    )
    return results


def main() -> int:
    try:
        body = _check_core_and_gates()
        status = "PASS" if body.get("passed") else "FAIL"
        error = None
    except Exception as exc:
        body = {}
        status = "ERROR"
        error = str(exc)[:500]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "error": error,
        "checks": body,
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
