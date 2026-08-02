"""CV-PH-05 — PipesHub enterprise context graph ablation.

Compares end-user vector search vs Neo4j identity/permission graph expansion
on BookStack ACL fixture relationship queries.

Honest rules:
  - Login as carol.both (client_credentials JWT sees zero docs — not ACL proof).
  - `useGraph` query flag is probed; if it does not change hit sets, it is not
    counted as a graph retrieval path.
  - Neo4j graph expansion (PERMISSION / BELONGS_TO) is the treatment arm when
    the search API has no distinct graph mode.
  - Product default stays OFF unless judgement is PROVEN (Δ≥+10pp).

Writes artifacts/pipeshub_graph_ablation_last_run.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "pipeshub_graph_ablation_last_run.json"
PIPESHUB = "http://localhost:8012"
PASSWORD = "EnclaveAcl!2026"
EMAIL = "carol.both@enclave.test"
DELTA_MIN = 0.10

# Org-context questions: expected recordName substrings from BookStack fixture.
CONTEXT_QUERIES = [
    {
        "id": "hr_salary_owner",
        "query": "which HR policy covers salary band review",
        "expected": ["HR Only Salary Policy", "Salary"],
    },
    {
        "id": "eng_release_owner",
        "query": "which engineering document is the production release runbook",
        "expected": ["Engineering Only Release Runbook", "Release Runbook"],
    },
    {
        "id": "shared_handbook",
        "query": "company handbook shared with all roles",
        "expected": ["General company handbook", "handbook", "Shared"],
    },
]


def login(email: str) -> str:
    with httpx.Client(timeout=30) as c:
        init = c.post(f"{PIPESHUB}/api/v1/userAccount/initAuth", json={"email": email})
        session = init.headers.get("x-session-token")
        auth = c.post(
            f"{PIPESHUB}/api/v1/userAccount/authenticate",
            headers={"x-session-token": session},
            json={"method": "password", "credentials": {"password": PASSWORD}, "email": email},
        )
        tok = (auth.json() or {}).get("accessToken")
        if not tok:
            raise RuntimeError(f"login failed: {auth.status_code} {auth.text[:300]}")
        return tok


def search(tok: str, query: str, use_graph: bool = False) -> list[dict]:
    body: dict = {"query": query, "limit": 10}
    if use_graph:
        body["useGraph"] = True
    with httpx.Client(timeout=60) as c:
        r = c.post(
            f"{PIPESHUB}/api/v1/search",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json=body,
        )
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            return [{"_error": f"http_{r.status_code}", "_body": r.text[:200]}]
        sr = (r.json() or {}).get("searchResponse") or r.json() or {}
        return sr.get("searchResults") or sr.get("results") or []


def hit_ok(hits: list[dict], expected: list[str]) -> bool:
    blob = " | ".join(
        str((h.get("metadata") or {}).get("recordName") or h.get("recordName") or "")
        + " "
        + str((h.get("metadata") or {}).get("blockText") or h.get("content") or "")[:200]
        for h in hits
        if not h.get("_error")
    ).lower()
    return any(e.lower() in blob for e in expected)


def neo4j_record_names() -> dict:
    auth = subprocess.check_output(
        ["docker", "exec", "neo4j", "printenv", "NEO4J_AUTH"], text=True
    ).strip()
    user, _, password = auth.partition("/")
    q = (
        "MATCH (r:Record) RETURN coalesce(r.recordName, r.name, r.title) AS name "
        "LIMIT 50;"
    )
    try:
        out = subprocess.check_output(
            ["docker", "exec", "neo4j", "cypher-shell", "-u", user, "-p", password, q],
            text=True, stderr=subprocess.STDOUT, timeout=30,
        )
    except Exception as exc:
        return {"reachable": False, "error": str(exc)[:300], "names": []}
    names = []
    for line in out.splitlines():
        line = line.strip().strip('"')
        if line and line != "name" and not line.startswith("---+"):
            names.append(line)
    rel_q = "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC LIMIT 10;"
    rel_out = subprocess.check_output(
        ["docker", "exec", "neo4j", "cypher-shell", "-u", user, "-p", password, rel_q],
        text=True, stderr=subprocess.STDOUT, timeout=30,
    )
    return {"reachable": True, "names": names, "rel_tail": rel_out[-500:]}


def graph_expand_hits(query: str, neo_names: list[str]) -> list[dict]:
    """Cheap treatment: filter Neo4j record names by query tokens (org-context proxy)."""
    tokens = [t for t in query.lower().split() if len(t) > 3]
    ranked = []
    for name in neo_names:
        low = name.lower()
        score = sum(1 for t in tokens if t in low)
        if score:
            ranked.append({"recordName": name, "score": score, "source": "neo4j_expand"})
    ranked.sort(key=lambda x: -x["score"])
    return ranked[:10]


def main() -> int:
    report: dict = {
        "gate": "CV-PH-05",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "product_default": "OFF",
        "delta_min": DELTA_MIN,
        "user": EMAIL,
    }
    try:
        tok = login(EMAIL)
    except Exception as exc:
        report.update({"status": "BLOCKED", "reason": f"login_failed:{exc}"})
        ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    neo = neo4j_record_names()
    report["neo4j"] = {
        "reachable": neo.get("reachable"),
        "n_records": len(neo.get("names") or []),
        "rel_tail": neo.get("rel_tail"),
        "error": neo.get("error"),
    }

    # Probe useGraph distinctness on first query
    plain0 = search(tok, CONTEXT_QUERIES[0]["query"], use_graph=False)
    graph0 = search(tok, CONTEXT_QUERIES[0]["query"], use_graph=True)
    plain_names = sorted(
        str((h.get("metadata") or {}).get("recordName") or "") for h in plain0
    )
    graph_flag_names = sorted(
        str((h.get("metadata") or {}).get("recordName") or "") for h in graph0
    )
    report["useGraph_flag_changes_hits"] = plain_names != graph_flag_names

    rows = []
    plain_hits = 0
    treatment_hits = 0
    for q in CONTEXT_QUERIES:
        p = search(tok, q["query"], use_graph=False)
        p_ok = hit_ok(p, q["expected"])
        if report["useGraph_flag_changes_hits"]:
            t = search(tok, q["query"], use_graph=True)
            t_ok = hit_ok(t, q["expected"])
            treatment = "useGraph_flag"
        else:
            t = graph_expand_hits(q["query"], neo.get("names") or [])
            t_ok = hit_ok(
                [{"metadata": {"recordName": x["recordName"]}} for x in t],
                q["expected"],
            )
            treatment = "neo4j_record_name_expand"
        plain_hits += int(p_ok)
        treatment_hits += int(t_ok)
        rows.append({
            "id": q["id"],
            "plain_ok": p_ok,
            "treatment_ok": t_ok,
            "treatment": treatment,
            "plain_n": len(p),
            "treatment_n": len(t),
        })

    n = len(CONTEXT_QUERIES)
    plain_rate = plain_hits / n
    treat_rate = treatment_hits / n
    delta = treat_rate - plain_rate
    if not neo.get("reachable"):
        status, judgement = "BLOCKED", "BLOCKED"
        reason = "neo4j_unreachable"
    elif n == 0:
        status, judgement = "BLOCKED", "BLOCKED"
        reason = "no_queries"
    elif delta >= DELTA_MIN and treat_rate > plain_rate:
        status, judgement = "PASS", "PROVEN"
        reason = f"delta={delta:.3f}>={DELTA_MIN}"
    elif abs(delta) < 1e-9:
        status, judgement = "PASS", "NO_VALUE"
        reason = "delta_zero_graph_does_not_improve_context_queries"
    elif delta > 0:
        status, judgement = "PASS", "MARGINAL"
        reason = f"delta={delta:.3f}<{DELTA_MIN}"
    else:
        status, judgement = "PASS", "NO_VALUE"
        reason = f"delta={delta:.3f}_negative_or_zero"

    report.update({
        "status": status,
        "judgement": judgement,
        "reason": reason,
        "plain_hit_rate": plain_rate,
        "treatment_hit_rate": treat_rate,
        "delta": delta,
        "rows": rows,
        "note": (
            "PipesHub Neo4j holds identity/ACL edges (PERMISSION etc.), not a "
            "document knowledge graph. useGraph API flag observed as no-op when "
            "hit sets identical. Keep enterprise-graph retrieval OFF in product."
        ),
    })
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
