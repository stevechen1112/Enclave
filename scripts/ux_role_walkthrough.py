"""
Role task-script smoke for enterprise UX readiness.
Logs in as employee / hr / admin and checks nav-relevant API access.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"

ACCOUNTS = [
    ("employee", "employee@example.com", "employee123"),
    ("hr", "hr_test@enclave.local", "hr123456"),
    ("admin", "admin@example.com", "admin123"),
]


def post_form(path: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def get_json(path: str, token: str) -> tuple[int, object]:
    req = urllib.request.Request(
        BASE + path,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def main() -> int:
    report: list[dict] = []
    for role, email, password in ACCOUNTS:
        row: dict = {"role": role, "email": email}
        try:
            tok = post_form("/auth/login/access-token", {"username": email, "password": password})
            token = tok["access_token"]
            row["login"] = "ok"
        except Exception as e:
            row["login"] = f"FAIL {e}"
            report.append(row)
            continue

        me_status, me = get_json("/users/me", token)
        row["me"] = me_status
        if isinstance(me, dict):
            row["me_role"] = me.get("role")

        # Experience bootstrap
        st, exp = get_json("/experience/bootstrap", token)
        row["bootstrap"] = st
        if isinstance(exp, dict):
            row["caps"] = exp.get("capabilities")
            row["home"] = exp.get("default_home")

        # Employee-critical: documents + ask surface
        st, _ = get_json("/documents/", token)
        row["documents"] = st

        # Admin-only should fail for employee
        st, _ = get_json("/agent/review?limit=1", token)
        row["review"] = st

        st, _ = get_json("/connectors/", token)
        row["connectors"] = st

        st, _ = get_json("/company/dashboard", token)
        row["company"] = st

        report.append(row)

    print(json.dumps(report, ensure_ascii=False, indent=2))

    # Assertions for enterprise IA
    by = {r["role"]: r for r in report}
    ok = True
    if by.get("employee", {}).get("login") != "ok":
        print("FAIL employee login", file=sys.stderr)
        ok = False
    else:
        if by["employee"].get("documents") != 200:
            print("FAIL employee documents", file=sys.stderr)
            ok = False
        if by["employee"].get("review") not in (401, 403, 404):
            # employee must NOT manage review
            if by["employee"].get("review") == 200:
                print("FAIL employee can access review", file=sys.stderr)
                ok = False
    if by.get("hr", {}).get("login") != "ok":
        print("FAIL hr login", file=sys.stderr)
        ok = False
    if by.get("admin", {}).get("login") != "ok":
        print("FAIL admin login", file=sys.stderr)
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
