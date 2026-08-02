"""BS-setup: build the BookStack ACL fixture that CV-PH-03 is judged against.

Creates two roles, three users and a book/chapter/page structure that exercises the
permission semantics the PipesHub connector actually projects:

  - role-scoped content permissions (explicit per-item overrides)
  - inherited permissions (page inherits from chapter inherits from book)
  - a revoked page, to prove removal propagates
  - a page visible to everyone, as the control

The resulting expectation matrix (subject x page -> visible?) is written to
testdata/golden/acl_matrix.json and consumed by eval_pipeshub_acl_live.py, so the
expected answers are generated from configuration rather than hand-annotated.

Requires a BookStack API token (Settings > Users > API tokens):
  BOOKSTACK_URL, BOOKSTACK_TOKEN_ID, BOOKSTACK_TOKEN_SECRET
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "testdata" / "golden" / "acl_matrix.json"

BASE = os.getenv("BOOKSTACK_URL", "http://localhost:8090").rstrip("/")
TOKEN_ID = os.getenv("BOOKSTACK_TOKEN_ID", "")
TOKEN_SECRET = os.getenv("BOOKSTACK_TOKEN_SECRET", "")

PASSWORD = os.getenv("BOOKSTACK_USER_PASSWORD", "EnclaveAcl!2026")

ROLES = [
    {"key": "hr", "display_name": "Enclave HR", "description": "HR reviewers"},
    {"key": "eng", "display_name": "Enclave Engineering", "description": "Engineering reviewers"},
]

USERS = [
    {"key": "alice", "name": "Alice HR", "email": "alice.hr@enclave.test", "roles": ["hr"]},
    {"key": "bob", "name": "Bob Eng", "email": "bob.eng@enclave.test", "roles": ["eng"]},
    {"key": "carol", "name": "Carol Both", "email": "carol.both@enclave.test", "roles": ["hr", "eng"]},
]

# visible_to lists role keys; None means "all roles"; [] means revoked from everyone.
# Distinct wording per page keeps retrieval queries unambiguous during CV-PH-03.
PAGES = [
    {"key": "hr_only", "name": "HR Only Salary Policy", "chapter": "hr_chapter",
     "visible_to": ["hr"], "body": "Salary band review procedure. Confidential to HR."},
    {"key": "hr_only_2", "name": "HR Only Disciplinary Procedure", "chapter": "hr_chapter",
     "visible_to": ["hr"], "body": "Disciplinary hearing steps and appeal window. HR restricted."},
    {"key": "hr_only_3", "name": "HR Only Recruitment Budget", "chapter": "hr_chapter",
     "visible_to": ["hr"], "body": "Headcount and recruitment budget allocation. HR restricted."},
    {"key": "eng_only", "name": "Engineering Only Release Runbook", "chapter": "eng_chapter",
     "visible_to": ["eng"], "body": "Production release runbook. Confidential to Engineering."},
    {"key": "eng_only_2", "name": "Engineering Only Incident Postmortem", "chapter": "eng_chapter",
     "visible_to": ["eng"], "body": "Database outage postmortem and root cause. Engineering restricted."},
    {"key": "eng_only_3", "name": "Engineering Only Secret Rotation", "chapter": "eng_chapter",
     "visible_to": ["eng"], "body": "Credential rotation schedule for production. Engineering restricted."},
    {"key": "shared", "name": "Shared Company Handbook", "chapter": "public_chapter",
     "visible_to": None, "body": "General company handbook, visible to every role."},
    {"key": "shared_2", "name": "Shared Office Safety Guide", "chapter": "public_chapter",
     "visible_to": None, "body": "Fire drill and office safety guidance for all staff."},
    {"key": "both_roles", "name": "Joint HR Engineering Onboarding", "chapter": "public_chapter",
     "visible_to": ["hr", "eng"], "body": "Onboarding checklist owned jointly by HR and Engineering."},
    {"key": "hr_inherited", "name": "HR Inherited Leave Policy", "chapter": "hr_chapter",
     "visible_to": ["hr"], "body": "Leave policy, inherits chapter permissions.", "inherit": True},
    {"key": "hr_inherited_2", "name": "HR Inherited Overtime Rules", "chapter": "hr_chapter",
     "visible_to": ["hr"], "body": "Overtime approval rules, inherits chapter permissions.", "inherit": True},
    {"key": "eng_inherited", "name": "Engineering Inherited Oncall", "chapter": "eng_chapter",
     "visible_to": ["eng"], "body": "Oncall rotation, inherits chapter permissions.", "inherit": True},
    {"key": "eng_inherited_2", "name": "Engineering Inherited Code Review", "chapter": "eng_chapter",
     "visible_to": ["eng"], "body": "Code review standards, inherits chapter permissions.", "inherit": True},
    {"key": "revoked", "name": "Revoked Draft Compensation Plan", "chapter": "hr_chapter",
     "visible_to": [], "body": "Draft withdrawn from all roles; must never be retrievable."},
    {"key": "revoked_2", "name": "Revoked Draft Layoff Memo", "chapter": "hr_chapter",
     "visible_to": [], "body": "Withdrawn layoff memo; must never be retrievable."},
    {"key": "revoked_3", "name": "Revoked Draft Vendor Contract", "chapter": "eng_chapter",
     "visible_to": [], "body": "Withdrawn vendor contract draft; must never be retrievable."},
]

CHAPTERS = {
    "hr_chapter": {"name": "HR Policies", "visible_to": ["hr"]},
    "eng_chapter": {"name": "Engineering Policies", "visible_to": ["eng"]},
    "public_chapter": {"name": "Company Wide", "visible_to": None},
}


def api(method: str, path: str, payload=None):
    headers = {"Authorization": f"Token {TOKEN_ID}:{TOKEN_SECRET}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}/api{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {detail[:400]}") from None


def find_by_name(listing_path: str, name: str):
    data = api("GET", f"{listing_path}?count=500").get("data", [])
    for item in data:
        if item.get("name") == name or item.get("display_name") == name:
            return item
    return None


# access-api is required for the per-user verification tokens to list content;
# without it BookStack rejects every API call from that role with HTTP 403.
ROLE_BASE_PERMISSIONS = ["access-api", "page-view-all", "chapter-view-all", "book-view-all"]


def ensure_role(spec: dict) -> dict:
    body = {
        "display_name": spec["display_name"],
        "description": spec["description"],
        # Baseline capabilities; per-content overrides are applied separately.
        "permissions": ROLE_BASE_PERMISSIONS,
    }
    existing = find_by_name("/roles", spec["display_name"])
    if existing:
        return api("PUT", f"/roles/{existing['id']}", body)
    return api("POST", "/roles", body)


def ensure_user(spec: dict, role_ids: list[int]) -> dict:
    data = api("GET", "/users?count=500").get("data", [])
    for u in data:
        if u.get("email") == spec["email"]:
            api("PUT", f"/users/{u['id']}", {"roles": role_ids})
            return u
    return api("POST", "/users", {
        "name": spec["name"], "email": spec["email"],
        "password": PASSWORD, "roles": role_ids, "send_invite": False,
    })


def ensure_book(name: str) -> dict:
    existing = find_by_name("/books", name)
    return existing or api("POST", "/books", {"name": name, "description": "CV-PH-03 ACL fixture"})


def ensure_chapter(book_id: int, name: str) -> dict:
    for c in api("GET", "/chapters?count=500").get("data", []):
        if c.get("name") == name and c.get("book_id") == book_id:
            return c
    return api("POST", "/chapters", {"book_id": book_id, "name": name})


def ensure_page(book_id: int, chapter_id: int, name: str, body: str) -> dict:
    for p in api("GET", "/pages?count=500").get("data", []):
        if p.get("name") == name and p.get("chapter_id") == chapter_id:
            return p
    return api("POST", "/pages", {
        "book_id": book_id, "chapter_id": chapter_id, "name": name,
        "markdown": body,
    })


def set_content_permissions(kind: str, item_id: int, role_ids: list[int], inherit: bool) -> None:
    """Apply explicit role permissions. role_ids == [] revokes access for everyone."""
    api("PUT", f"/content-permissions/{kind}/{item_id}", {
        "owner_id": 1,
        "fallback_permissions": {"inheriting": inherit} if inherit else {
            "inheriting": False, "view": False, "create": False, "update": False, "delete": False,
        },
        "role_permissions": [
            {"role_id": rid, "view": True, "create": False, "update": False, "delete": False}
            for rid in role_ids
        ],
    })


def main() -> int:
    if not (TOKEN_ID and TOKEN_SECRET):
        print("BOOKSTACK_TOKEN_ID / BOOKSTACK_TOKEN_SECRET must be set.")
        print("Create one at http://localhost:8090/my-account/auth (API tokens).")
        return 2

    roles = {}
    for spec in ROLES:
        role = ensure_role(spec)
        roles[spec["key"]] = role
        print(f"role {spec['key']:4s} -> id={role['id']}")

    for spec in USERS:
        user = ensure_user(spec, [roles[r]["id"] for r in spec["roles"]])
        print(f"user {spec['key']:6s} -> id={user['id']} roles={spec['roles']}")

    book = ensure_book("Enclave ACL Fixture")
    print(f"book -> id={book['id']}")

    chapters = {}
    for key, spec in CHAPTERS.items():
        ch = ensure_chapter(book["id"], spec["name"])
        chapters[key] = ch
        role_ids = ([roles[r]["id"] for r in spec["visible_to"]] if spec["visible_to"] is not None
                    else [r["id"] for r in roles.values()])
        set_content_permissions("chapter", ch["id"], role_ids, inherit=False)
        print(f"chapter {key:15s} -> id={ch['id']} roles={spec['visible_to']}")

    pages = {}
    for spec in PAGES:
        ch = chapters[spec["chapter"]]
        page = ensure_page(book["id"], ch["id"], spec["name"], spec["body"])
        pages[spec["key"]] = page
        if spec.get("inherit"):
            set_content_permissions("page", page["id"], [], inherit=True)
        else:
            role_ids = ([roles[r]["id"] for r in spec["visible_to"]] if spec["visible_to"] is not None
                        else [r["id"] for r in roles.values()])
            set_content_permissions("page", page["id"], role_ids, inherit=False)
        print(f"page {spec['key']:14s} -> id={page['id']} visible_to={spec['visible_to']} "
              f"inherit={bool(spec.get('inherit'))}")

    # Expected visibility is derived from configuration, so the matrix needs no annotation.
    expectations = []
    for user in USERS:
        for spec in PAGES:
            chapter_vis = CHAPTERS[spec["chapter"]]["visible_to"]
            effective = chapter_vis if spec.get("inherit") else spec["visible_to"]
            visible = True if effective is None else bool(set(effective) & set(user["roles"]))
            expectations.append({
                "user": user["key"],
                "user_email": user["email"],
                "page": spec["key"],
                "page_name": spec["name"],
                "page_id": pages[spec["key"]]["id"],
                "expected_visible": visible,
                "case": ("inherited" if spec.get("inherit")
                         else "revoked" if spec["visible_to"] == []
                         else "shared" if spec["visible_to"] is None
                         else "multi_role" if len(spec["visible_to"]) > 1
                         else "explicit_role"),
            })

    matrix = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "bookstack",
        "base_url": BASE,
        "book_id": book["id"],
        "roles": {k: v["id"] for k, v in roles.items()},
        "users": {u["key"]: u["email"] for u in USERS},
        "pairs": len(expectations),
        "expected_visible": sum(1 for e in expectations if e["expected_visible"]),
        "expected_hidden": sum(1 for e in expectations if not e["expected_visible"]),
        "matrix": expectations,
    }
    OUT.write_text(json.dumps(matrix, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\npairs={matrix['pairs']} visible={matrix['expected_visible']} hidden={matrix['expected_hidden']}")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
