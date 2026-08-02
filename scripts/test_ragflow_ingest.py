"""Quick RAGFlow ingest poll test."""
import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from app.core.authorization import AuthorizationContext
from app.gateway.adapters.ragflow_http import RAGFlowHTTPAdapter
from app.services.content_reference import build_content_reference, resolve_content_bytes


async def main():
    adapter = RAGFlowHTTPAdapter(
        base_url=os.environ["RAGFLOW_BASE_URL"],
        api_key=os.environ["RAGFLOW_API_KEY"],
    )
    authz = AuthorizationContext(
        tenant_id=uuid.uuid4(), subject_id=uuid.uuid4(), is_superuser=True,
    )
    doc_id = uuid.uuid4()
    f = ROOT / "tests" / "fixtures" / "sample.txt"
    ref, meta = build_content_reference(str(f), authz.tenant_id, doc_id)
    meta["file_bytes"] = resolve_content_bytes(ref, meta)
    meta["dataset_id"] = os.environ["RAGFLOW_DATASET_ID"]
    r = await adapter.ingest(doc_id, 1, ref, "hash", "txt", authz, metadata=meta)
    print("ingest", r)
    jid = (r.get("ragflow_doc_ids") or [None])[0]
    if not jid:
        return
    for i in range(15):
        pr = await adapter.get_parse_result(jid)
        n = len(pr.get("chunks", []))
        print(f"poll {i}", pr.get("status"), n, pr.get("run", pr.get("error", "")))
        if n:
            print("chunk0", pr["chunks"][0].get("text", "")[:120])
            break
        await asyncio.sleep(3)


asyncio.run(main())
