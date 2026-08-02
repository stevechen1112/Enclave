"""D5 — create/enable a WeKnora KB with graph_enabled + extract, ingest docs.

Requires WeKnora-neo4j up and NEO4J_ENABLE=true on WeKnora-app.
Does NOT flip product fan-out; CV-WK-05 ablation remains separate.

Writes artifacts/weknora_graph_kb_setup_last_run.json.
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
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "weknora_graph_kb_setup_last_run.json"
CORPUS = [
    ROOT / "testdata" / "golden" / "esg" / "GRI_101.pdf",
    ROOT / "testdata" / "golden" / "esg" / "GRI_102.pdf",
    ROOT / "testdata" / "golden" / "esg" / "GRI_103.pdf",
]


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
        "gate": "D5",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
    }

    # Resolve embedding + chat model ids from existing list
    with httpx.Client(base_url=base, headers=_headers(), timeout=60.0) as client:
        # Health / neo4j probe via system if available
        for path in ("/api/v1/health", "/health"):
            try:
                r = client.get(path)
                report.setdefault("health", {})[path] = {"status": r.status_code, "body": r.text[:200]}
            except Exception as exc:
                report.setdefault("health", {})[path] = {"error": str(exc)[:200]}

        models = client.get("/api/v1/models", params={"page": 1, "page_size": 100})
        model_list = []
        if models.status_code == 200:
            data = models.json().get("data") or models.json()
            if isinstance(data, dict):
                model_list = data.get("items") or data.get("list") or []
            elif isinstance(data, list):
                model_list = data
        emb_id = next(
            (m.get("id") for m in model_list
             if "embed" in str(m.get("type", "")).lower()
             or "bge" in str(m.get("name", "")).lower()
             or "embedding" in str(m.get("model_type", "")).lower()),
            None,
        )
        chat_id = next(
            (m.get("id") for m in model_list
             if m.get("id") != emb_id and (
                 "chat" in str(m.get("type", "")).lower()
                 or "KnowledgeQA" in str(m.get("type", ""))
                 or "llama" in str(m.get("name", "")).lower()
                 or "qwen" in str(m.get("name", "")).lower()
             )),
            None,
        )
        # fallback: any two models
        if not emb_id and model_list:
            emb_id = model_list[0].get("id")
        if not chat_id and len(model_list) > 1:
            chat_id = model_list[1].get("id")
        report["models"] = {"embedding_id": emb_id, "chat_id": chat_id, "n": len(model_list)}

        # Reuse existing graph KB if present
        kbs = client.get("/api/v1/knowledge-bases", params={"page": 1, "page_size": 100})
        kb_id = None
        for kb in (kbs.json().get("data") or []):
            ge = bool(
                (kb.get("indexing_strategy") or {}).get("graph_enabled")
                or (kb.get("capabilities") or {}).get("graph")
            )
            if ge or kb.get("name") == "Enclave Graph KB":
                kb_id = kb.get("id")
                report["reused_kb"] = {"id": kb_id, "name": kb.get("name"), "graph": ge}
                break

        if not kb_id:
            body = {
                "name": "Enclave Graph KB",
                "description": "D5 GraphRAG ablation KB (ADR-007 weknora.neo4j namespace)",
                "type": "document",
                "indexing_strategy": {
                    "vector_enabled": True,
                    "keyword_enabled": True,
                    "wiki_enabled": False,
                    "graph_enabled": True,
                },
                "extract_config": {
                    "enabled": True,
                    "text": "Extract organizations, metrics, and causal relations from ESG standards.",
                    "tags": ["organization", "metric", "regulation", "risk"],
                },
            }
            if emb_id:
                body["embedding_model_id"] = emb_id
            if chat_id:
                body["summary_model_id"] = chat_id
            created = client.post("/api/v1/knowledge-bases", json=body)
            report["create"] = {"status": created.status_code, "body": created.text[:500]}
            if created.status_code not in (200, 201):
                # try nested config shape
                body2 = {
                    "name": "Enclave Graph KB",
                    "description": "D5 GraphRAG ablation KB",
                    "config": {
                        "indexing_strategy": body["indexing_strategy"],
                        "extract_config": body["extract_config"],
                    },
                }
                created = client.post("/api/v1/knowledge-bases", json=body2)
                report["create_retry"] = {"status": created.status_code, "body": created.text[:500]}
            if created.status_code in (200, 201):
                data = created.json().get("data") or created.json()
                kb_id = data.get("id") if isinstance(data, dict) else None
            if not kb_id:
                report["status"] = "BLOCKED"
                report["reason"] = "could_not_create_graph_kb"
                ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 1

        report["kb_id"] = kb_id

        # Upload available corpus files
        uploads = []
        for path in CORPUS:
            if not path.exists():
                # fall back: any pdf under testdata/golden
                continue
            with path.open("rb") as f:
                resp = client.post(
                    f"/api/v1/knowledge-bases/{kb_id}/knowledge/file",
                    files={"file": (path.name, f, "application/pdf")},
                )
            uploads.append({"file": path.name, "status": resp.status_code, "body": resp.text[:200]})
        if not uploads:
            # discover wiki KB source files or any pdf
            candidates = list((ROOT / "testdata").rglob("*.pdf"))[:3]
            for path in candidates:
                with path.open("rb") as f:
                    resp = client.post(
                        f"/api/v1/knowledge-bases/{kb_id}/knowledge/file",
                        files={"file": (path.name, f, "application/pdf")},
                    )
                uploads.append({"file": str(path), "status": resp.status_code, "body": resp.text[:200]})
        report["uploads"] = uploads

        # Poll knowledge list briefly
        time.sleep(5)
        listed = client.get(f"/api/v1/knowledge-bases/{kb_id}/knowledge", params={"page": 1, "page_size": 50})
        report["knowledge_list"] = {"status": listed.status_code, "sample": listed.text[:400]}

        # Re-check graph flag
        detail = client.get(f"/api/v1/knowledge-bases/{kb_id}")
        kb = (detail.json().get("data") or {}) if detail.status_code == 200 else {}
        ge = bool(
            (kb.get("indexing_strategy") or {}).get("graph_enabled")
            or (kb.get("capabilities") or {}).get("graph")
            or ((kb.get("extract_config") or {}).get("enabled"))
        )
        report["graph_enabled"] = ge
        report["kb_detail_sample"] = {
            "name": kb.get("name"),
            "indexing_strategy": kb.get("indexing_strategy"),
            "capabilities": kb.get("capabilities"),
            "extract_config_enabled": (kb.get("extract_config") or {}).get("enabled"),
        }
        report["status"] = "READY" if ge else "BLOCKED"
        report["reason"] = "graph_kb_ready" if ge else "graph_flag_not_set_on_kb"

    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
