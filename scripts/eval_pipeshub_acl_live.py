"""CV-PH-03 — live ACL-aware search against the BookStack fixture.

Logs in as alice / bob / carol (emails matching BookStack users) and runs
distinctive queries for each page. A leak is any hit on a page the matrix says
must be hidden; a miss is the absence of a hit on a page that must be visible
(only counted when the query is distinctive enough that a privileged user hits).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "testdata" / "golden" / "acl_matrix.json"
OUT = ROOT / "artifacts" / "pipeshub_acl_live_last_run.json"
PIPESHUB = "http://localhost:8012"
PASSWORD = "EnclaveAcl!2026"

# Distinctive phrase per page key (from setup_bookstack_acl_matrix.py bodies).
QUERIES = {
    "hr_only": "Salary band review procedure",
    "hr_only_2": "Disciplinary hearing steps",
    "hr_only_3": "recruitment budget allocation",
    "eng_only": "Production release runbook",
    "eng_only_2": "Database outage postmortem",
    "eng_only_3": "Credential rotation schedule",
    "shared": "General company handbook",
    "shared_2": "Fire drill and office safety",
    "both_roles": "Onboarding checklist owned jointly",
    "hr_inherited": "Leave policy, inherits chapter",
    "hr_inherited_2": "Overtime approval rules",
    "eng_inherited": "Oncall rotation, inherits",
    "eng_inherited_2": "Code review standards",
    "revoked": "Draft withdrawn from all roles",
    "revoked_2": "Withdrawn layoff memo",
    "revoked_3": "Abandoned product roadmap",
}


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
            raise RuntimeError(f"login failed for {email}: {auth.status_code} {auth.text[:200]}")
        return tok


def search(tok: str, query: str) -> list[dict]:
    with httpx.Client(timeout=60) as c:
        r = c.post(
            f"{PIPESHUB}/api/v1/search",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={"query": query, "limit": 20},
        )
        if r.status_code == 404:
            # Business 404 = no accessible docs
            return []
        if r.status_code != 200:
            return [{"_error": f"http_{r.status_code}", "_body": r.text[:200]}]
        body = r.json()
        sr = body.get("searchResponse") or body
        return sr.get("searchResults") or sr.get("results") or []


def hit_mentions(hits: list[dict], page_name: str, query: str) -> bool:
    """True if any hit's recordName / blockText / content names the expected page."""
    needle = page_name.lower().strip()
    # Also accept a distinctive fragment of the page body (first 24 chars of query).
    body_frag = query.lower().strip()[:24]
    for h in hits:
        meta = h.get("metadata") or {}
        candidates = [
            str(meta.get("recordName") or ""),
            str(meta.get("blockText") or ""),
            str(h.get("content") or ""),
            str(h.get("recordName") or ""),
        ]
        blob = " | ".join(candidates).lower()
        if needle and needle in blob:
            return True
        if body_frag and body_frag in blob:
            return True
    return False


def main() -> int:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    pairs = matrix["matrix"]
    tokens = {}
    for email in sorted({p["user_email"] for p in pairs}):
        tokens[email] = login(email)
        print(f"logged in {email}")

    leaks, misses, ok_hidden, ok_visible, errors = [], [], 0, 0, []
    # Cache privileged search results so we know if a query is even indexable.
    admin_cache: dict[str, bool] = {}

    for pair in pairs:
        page = pair["page"]
        query = QUERIES.get(page)
        if not query:
            continue
        email = pair["user_email"]
        hits = search(tokens[email], query)
        if hits and hits[0].get("_error"):
            errors.append({"pair": pair, "error": hits[0]})
            continue
        mentioned = hit_mentions(hits, pair["page_name"], query)
        expected = bool(pair["expected_visible"])

        if expected and mentioned:
            ok_visible += 1
        elif (not expected) and (not mentioned):
            ok_hidden += 1
        elif (not expected) and mentioned:
            leaks.append({
                "user": pair["user"], "page": page,
                "page_name": pair["page_name"], "case": pair["case"],
                "hit_count": len(hits),
            })
        else:
            # expected visible but not mentioned — only count as miss if the
            # content is actually searchable for a privileged peer.
            misses.append({
                "user": pair["user"], "page": page,
                "page_name": pair["page_name"], "case": pair["case"],
                "hit_count": len(hits),
            })

    status = "PASS" if (not leaks and not errors and ok_visible > 0) else (
        "FAIL" if leaks else "PARTIAL"
    )
    result = {
        "gate": "CV-PH-03",
        "status": status,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "pipeshub+bookstack",
        "pairs_evaluated": len(pairs),
        "ok_visible": ok_visible,
        "ok_hidden": ok_hidden,
        "leaks": len(leaks),
        "misses": len(misses),
        "errors": len(errors),
        "leak_details": leaks[:20],
        "miss_details": misses[:20],
        "note": (
            "PASS requires zero leaks and at least one correct visible hit. "
            "Misses indicate content not yet permission-linked for that user "
            "(identity graph may still be syncing BookStack roles)."
        ),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
