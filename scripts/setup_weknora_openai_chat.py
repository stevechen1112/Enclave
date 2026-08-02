"""Register OpenAI gpt-5.6-luna as WeKnora KnowledgeQA model.

Sets it as the default chat model and points existing graph/wiki KBs'
summary_model_id at it, so GraphRAG extract / Wiki synthesis use the
cloud model instead of local 8B. Idempotent.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "weknora_openai_model_last_run.json"
CHAT_NAME = os.getenv("WEKNORA_OPENAI_CHAT_MODEL", "gpt-5.6-luna")


def _load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k.startswith("WEKNORA_"):
                os.environ[k] = v
            else:
                os.environ.setdefault(k, v)


def _headers() -> dict:
    key = os.getenv("WEKNORA_API_KEY", "")
    if key.startswith("sk-"):
        return {"X-API-Key": key}
    return {"Authorization": f"Bearer {key}"} if key else {}


def main() -> int:
    _load_env()
    base = os.getenv("WEKNORA_BASE_URL", "http://localhost:8081").rstrip("/")
    report: dict = {
        "gate": "WK-OPENAI",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": CHAT_NAME,
    }

    with httpx.Client(base_url=base, headers=_headers(), timeout=60.0) as client:
        models = client.get("/api/v1/models", params={"page": 1, "page_size": 100})
        data = models.json().get("data") or models.json()
        model_list = data.get("items") or data.get("list") or [] if isinstance(data, dict) else data
        existing = next((m for m in model_list if m.get("name") == CHAT_NAME), None)

        if existing:
            model_id = existing.get("id")
            report["action"] = "reused"
        else:
            created = client.post("/api/v1/models", json={
                "name": CHAT_NAME,
                "display_name": f"OpenAI {CHAT_NAME}",
                "type": "KnowledgeQA",
                "source": "openai",
                "description": "Cloud chat model for GraphRAG extract / Wiki synthesis",
                "parameters": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key": os.environ["OPENAI_API_KEY"],
                    "provider": "openai",
                },
            })
            report["create"] = {"status": created.status_code, "body": created.text[:400]}
            if created.status_code not in (200, 201):
                report["status"] = "FAIL"
                report["reason"] = "model_create_failed"
                ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 1
            body = created.json().get("data") or created.json()
            model_id = body.get("id") if isinstance(body, dict) else None
            report["action"] = "created"

        report["model_id"] = model_id

        # Point existing graph / wiki KBs at the new chat model.
        # PUT /knowledge-bases/:id requires name + full config object.
        kbs = client.get("/api/v1/knowledge-bases", params={"page": 1, "page_size": 100})
        kb_updates = []
        for kb in (kbs.json().get("data") or []):
            kb_id = kb.get("id")
            name = kb.get("name", "")
            if not any(t in name for t in ("Graph KB", "Wiki KB")):
                continue
            detail = client.get(f"/api/v1/knowledge-bases/{kb_id}")
            if detail.status_code != 200:
                kb_updates.append({"kb": name, "id": kb_id, "status": detail.status_code,
                                   "body": "detail_fetch_failed"})
                continue
            full = detail.json().get("data") or {}
            config = full.get("config") or {}
            config["summary_model_id"] = model_id
            r = client.put(f"/api/v1/knowledge-bases/{kb_id}", json={
                "name": name,
                "description": full.get("description") or "",
                "config": config,
            })
            kb_updates.append({"kb": name, "id": kb_id, "status": r.status_code,
                               "body": r.text[:200]})
        report["kb_updates"] = kb_updates

        report["status"] = "PASS"
        report["reason"] = "openai_chat_registered_and_kbs_updated"

    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
