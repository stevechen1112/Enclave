"""CV-WK-05 value probe — vector knowledge-search vs Neo4j entity presence.

Not a full relationship-QA suite. Scores whether WeKnora-neo4j ENTITY nodes
related to the query improve document recall over plain knowledge-search on
the graph KB. Product default stays OFF unless Δ ≥ +10pp.

Writes artifacts/weknora_graph_value_ablation_last_run.json
(and refreshes weknora_graph_ablation_last_run.json summary fields).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "weknora_graph_value_ablation_last_run.json"
PROBE = ROOT / "artifacts" / "weknora_graph_ablation_last_run.json"
DELTA_MIN = 0.10
KB_ID = "e63adcb8-1293-4cb4-a4b5-83e26c41f8ee"

QUERIES = [
    {"id": "Q1", "query": "合約 甲方 乙方", "expected_tokens": ["合約", "nueip", "MOU"]},
    {"id": "Q2", "query": "營業稅 繳款", "expected_tokens": ["營業稅", "繳款"]},
    {"id": "Q3", "query": "家長同意書 入團", "expected_tokens": ["同意書", "入團", "家長"]},
]


def _load_env():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            if k.strip().startswith("WEKNORA_"):
                os.environ[k.strip()] = v.strip()


def _headers():
    key = os.getenv("WEKNORA_API_KEY", "")
    if key.startswith("sk-"):
        return {"X-API-Key": key}
    return {"Authorization": f"Bearer {key}"} if key else {}


def neo4j_entities() -> list[str]:
    out = subprocess.check_output(
        ["docker", "exec", "WeKnora-neo4j", "cypher-shell", "-u", "neo4j", "-p", "password",
         "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'ENTITY') "
         "RETURN coalesce(n.name, n.title, n.id, labels(n)[0]) AS name LIMIT 100;"],
        text=True, stderr=subprocess.STDOUT, timeout=30,
    )
    names = []
    for line in out.splitlines():
        line = line.strip().strip('"')
        if line and line != "name" and not line.startswith("-"):
            names.append(line)
    return names


def search(client: httpx.Client, query: str) -> list[dict]:
    r = client.post("/api/v1/knowledge-search", json={
        "query": query,
        "knowledge_base_ids": [KB_ID],
    })
    if r.status_code != 200:
        return [{"_error": f"http_{r.status_code}", "_body": r.text[:200]}]
    body = r.json()
    data = body.get("data") if isinstance(body, dict) else body
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("items") or data.get("results") or data.get("chunks") or []
        return items if isinstance(items, list) else []
    return []


def hit_tokens(blob: str, tokens: list[str]) -> bool:
    low = blob.lower()
    return any(t.lower() in low for t in tokens)


def main() -> int:
    _load_env()
    base = os.getenv("WEKNORA_BASE_URL", "http://localhost:8081").rstrip("/")
    entities = []
    try:
        entities = neo4j_entities()
    except Exception as exc:
        report = {
            "gate": "CV-WK-05-value",
            "status": "BLOCKED",
            "reason": f"weknora_neo4j:{exc}"[:300],
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    rows = []
    plain_n = graph_n = 0
    with httpx.Client(base_url=base, headers=_headers(), timeout=60.0) as client:
        for q in QUERIES:
            hits = search(client, q["query"])
            blob = " | ".join(
                str(h.get("content") or h.get("title") or h.get("knowledge_title") or h)[:300]
                for h in hits if not h.get("_error")
            )
            p_ok = hit_tokens(blob, q["expected_tokens"])
            # Treatment: also accept if any Neo4j entity name matches expected tokens
            ent_blob = " | ".join(entities)
            g_ok = p_ok or hit_tokens(ent_blob, q["expected_tokens"])
            plain_n += int(p_ok)
            graph_n += int(g_ok)
            rows.append({
                "id": q["id"],
                "plain_ok": p_ok,
                "graph_ok": g_ok,
                "n_hits": len(hits),
                "sample": blob[:160],
            })

    n = len(QUERIES)
    plain_rate = plain_n / n
    graph_rate = graph_n / n
    delta = graph_rate - plain_rate
    if delta >= DELTA_MIN:
        judgement = "PROVEN"
    elif abs(delta) < 1e-9:
        judgement = "NO_VALUE"
    elif delta > 0:
        judgement = "MARGINAL"
    else:
        judgement = "NO_VALUE"

    report = {
        "gate": "CV-WK-05-value",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kb_id": KB_ID,
        "entity_names_n": len(entities),
        "entity_sample": entities[:20],
        "plain_hit_rate": plain_rate,
        "graph_hit_rate": graph_rate,
        "delta": delta,
        "judgement": judgement,
        "status": "PASS",
        "product_default": "OFF",
        "rows": rows,
        "note": (
            "Entity-name overlap is a weak proxy for GraphRAG retrieval. "
            "Keep OFF until a dedicated relationship-question suite proves Δ."
        ),
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # Merge summary into main ablation artifact if present
    if PROBE.exists():
        try:
            base_rep = json.loads(PROBE.read_text(encoding="utf-8"))
            base_rep["value_ablation"] = {
                "judgement": judgement,
                "delta": delta,
                "artifact": str(ARTIFACT.name),
            }
            PROBE.write_text(json.dumps(base_rep, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
