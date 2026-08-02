"""Verify RAGFlow + WeKnora real Docker integration (no commit required)."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

# Load .env from project root
root = Path(__file__).resolve().parents[1]
env_path = root / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(root))


async def main() -> int:
    print("=== Enclave Sidecar Integration Check ===\n")

    from app.gateway.adapters.ragflow_http import RAGFlowHTTPAdapter
    from app.gateway.adapters.weknora_http import WeKnoraHTTPAdapter
    from app.gateway.adapter_factory import build_gateway_adapters
    from app.core.authorization import AuthorizationContext

    ragflow = RAGFlowHTTPAdapter(
        base_url=os.getenv("RAGFLOW_BASE_URL", "http://localhost:9380"),
        api_key=os.getenv("RAGFLOW_API_KEY", ""),
    )
    weknora = WeKnoraHTTPAdapter(
        base_url=os.getenv("WEKNORA_BASE_URL", "http://localhost:8081"),
        api_key=os.getenv("WEKNORA_API_KEY", ""),
    )

    rh = await ragflow.health()
    wh = await weknora.health()
    print(f"RAGFlow health: {rh}")
    print(f"WeKnora health: {wh}")

    authz = AuthorizationContext(
        tenant_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        is_superuser=True,
    )

    # WeKnora KB list
    import httpx
    token = os.getenv("WEKNORA_API_KEY", "")
    kb_resp = httpx.get(
        f"{os.getenv('WEKNORA_BASE_URL')}/api/v1/knowledge-bases",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    print(f"WeKnora KB list: {kb_resp.status_code} {kb_resp.text[:200]}")

    wiki_search = await weknora.search(authz, "test", top_k=3)
    print(f"WeKnora search results: {len(wiki_search)}")

    adapters = build_gateway_adapters()
    print(f"Gateway adapters: {list(adapters.keys())}")

    # Parse sample via RAGFlow if sample exists
    sample = root / "tests" / "fixtures" / "sample.txt"
    if not sample.exists():
        sample.write_text("Enclave sidecar integration test document.\n製造業品質手冊測試段落。", encoding="utf-8")

    from app.services.parse_pipeline import parse_document
    doc_id = uuid.uuid4()
    text, meta, artifact = parse_document(str(sample), "txt", doc_id, revision=1)
    print(f"\nParse engine: {meta.get('parse_engine')}")
    print(f"Parse route: {meta.get('parse_route')}")
    print(f"Chunks: {len(artifact.chunks)} confidence={artifact.confidence}")
    print(f"Text preview: {text[:120]}...")

    ok_ragflow = rh.get("status") == "healthy" and os.getenv("RAGFLOW_DATASET_ID")
    ok_weknora = wh.get("status") == "healthy" and kb_resp.status_code == 200

    pipeshub_ok = True
    if os.getenv("PIPESHUB_ENABLED", "").lower() == "true":
        from app.gateway.adapters.pipeshub_http import PipesHubHTTPAdapter
        pipeshub = PipesHubHTTPAdapter(
            base_url=os.getenv("PIPESHUB_BASE_URL", "http://localhost:8012"),
            api_key=os.getenv("PIPESHUB_API_KEY", ""),
        )
        ph = await pipeshub.health()
        print(f"PipesHub health: {ph}")
        pipeshub_search = await pipeshub.search(authz, "quality", top_k=3)
        print(f"PipesHub search results: {len(pipeshub_search)}")
        pipeshub_ok = ph.get("status") in ("healthy", "degraded")

    ok_parse = "ragflow" in str(meta.get("parse_engine", "")) or artifact.chunks

    print("\n=== Summary ===")
    print(f"RAGFlow reachable + dataset: {'OK' if ok_ragflow else 'FAIL'}")
    print(f"WeKnora auth + API: {'OK' if ok_weknora else 'FAIL'}")
    if os.getenv("PIPESHUB_ENABLED", "").lower() == "true":
        print(f"PipesHub API: {'OK' if pipeshub_ok else 'FAIL'}")
    print(f"Parse pipeline: {'OK' if ok_parse else 'PARTIAL (check logs)'}")

    all_ok = ok_ragflow and ok_weknora
    if os.getenv("PIPESHUB_ENABLED", "").lower() == "true":
        all_ok = all_ok and pipeshub_ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
