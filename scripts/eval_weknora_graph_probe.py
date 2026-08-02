"""D5 / CV-WK-05 probe — Neo4j reachability + WeKnora graph inventory.

Does NOT enable GraphRAG in product. Records:
  - Neo4j bolt reachable and node count (shared instance may hold PipesHub data)
  - WeKnora KB graph_enabled flags
  - Whether any WeKnora-namespaced evidence exists for ablation

If WeKnora has no graph-extracted entities for the wiki KB, status=BLOCKED
(ablation cannot run honestly). ADR-007 remains the boundary doc.
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
ARTIFACT = ROOT / "artifacts" / "weknora_graph_ablation_last_run.json"


def _load_env():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def neo4j_count() -> dict:
    """Prefer WeKnora-neo4j (ADR-007 namespace); fall back to shared PipesHub neo4j."""
    candidates = [
        ("WeKnora-neo4j", "neo4j", "password"),
        ("neo4j", None, None),  # auth from NEO4J_AUTH
    ]
    last_err = None
    for container, user, password in candidates:
        try:
            if password is None:
                auth = subprocess.check_output(
                    ["docker", "exec", container, "printenv", "NEO4J_AUTH"], text=True
                ).strip()
                user, _, password = auth.partition("/")
            out = subprocess.check_output(
                ["docker", "exec", container, "cypher-shell", "-u", user, "-p", password,
                 "MATCH (n) RETURN count(n) AS nodes;"],
                text=True, stderr=subprocess.STDOUT, timeout=30,
            )
            nodes = None
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    nodes = int(line)
            # Entity label sample (WeKnora uses ENTITY{kb}_{doc} labels)
            ent = subprocess.check_output(
                ["docker", "exec", container, "cypher-shell", "-u", user, "-p", password,
                 "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'ENTITY') "
                 "RETURN count(n) AS entities;"],
                text=True, stderr=subprocess.STDOUT, timeout=30,
            )
            entities = None
            for line in ent.splitlines():
                line = line.strip()
                if line.isdigit():
                    entities = int(line)
            return {
                "reachable": True,
                "container": container,
                "nodes": nodes,
                "weknora_entity_nodes": entities,
                "raw_tail": out[-200:],
            }
        except Exception as exc:
            last_err = str(exc)[:300]
            continue
    return {"reachable": False, "error": last_err or "no_neo4j_container"}


def weknora_graph_inventory() -> dict:
    base = os.getenv("WEKNORA_BASE_URL", "http://localhost:8081").rstrip("/")
    key = os.getenv("WEKNORA_API_KEY", "")
    headers = {}
    if key.startswith("sk-"):
        headers["X-API-Key"] = key
    elif key:
        headers["Authorization"] = f"Bearer {key}"
    out = {"base_url": base, "knowledge_bases": [], "graph_enabled_any": False}
    try:
        with httpx.Client(timeout=20.0) as client:
            # list KBs — path may vary; try common ones
            for path in ("/api/v1/knowledge-bases", "/api/v1/knowledgebases",
                         "/api/v1/tenants/knowledge-bases"):
                resp = client.get(f"{base}{path}", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data") or data.get("knowledge_bases") or data
                    if isinstance(items, dict):
                        items = items.get("items") or items.get("list") or []
                    if isinstance(items, list):
                        for kb in items:
                            if not isinstance(kb, dict):
                                continue
                            ge = bool(
                                (kb.get("indexing_strategy") or {}).get("graph_enabled")
                                or kb.get("graph_enabled")
                                or (kb.get("capabilities") or {}).get("graph")
                            )
                            out["knowledge_bases"].append({
                                "id": kb.get("id"),
                                "name": kb.get("name"),
                                "graph_enabled": ge,
                                "type": kb.get("type"),
                            })
                            out["graph_enabled_any"] = out["graph_enabled_any"] or ge
                        out["list_path"] = path
                        break
                    out.setdefault("attempts", []).append(
                        {"path": path, "status": resp.status_code, "sample": str(data)[:120]}
                    )
                else:
                    out.setdefault("attempts", []).append(
                        {"path": path, "status": resp.status_code}
                    )
    except Exception as exc:
        out["error"] = str(exc)[:300]
    return out


def main() -> int:
    _load_env()
    neo = neo4j_count()
    wk = weknora_graph_inventory()
    # Honest gate: cannot claim GraphRAG value without WeKnora graph_enabled KB
    # + WeKnora-namespaced entity nodes (not PipesHub identity graph).
    entities = neo.get("weknora_entity_nodes") or 0
    if not neo.get("reachable"):
        status = "BLOCKED"
        reason = "neo4j_unreachable"
    elif not wk.get("graph_enabled_any"):
        status = "BLOCKED"
        reason = "no_weknora_kb_with_graph_enabled"
    elif neo.get("container") != "WeKnora-neo4j":
        status = "BLOCKED"
        reason = "weknora_neo4j_not_running_shared_pipeshub_neo4j_only"
    elif entities <= 0:
        status = "READY"
        reason = "graph_kb_enabled_but_no_entity_nodes_yet"
    else:
        status = "READY"
        reason = (
            f"graph_extract_evidence_present entities={entities} "
            "ablation_delta_not_yet_proven"
        )

    report = {
        "gate": "CV-WK-05",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": status,
        "reason": reason,
        "judgement": "WIRING_PASS" if entities > 0 else status,
        "adr": "docs/adr/ADR-007-graph-store-boundary.md",
        "neo4j": neo,
        "weknora": wk,
        "product_default": "OFF",
        "note": (
            "Use WeKnora-neo4j entity counts as GraphRAG evidence — never PipesHub "
            "neo4j PERMISSION/Record counts. Value ablation (relationship Hit@K Δ) "
            "still required before product ON."
        ),
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
