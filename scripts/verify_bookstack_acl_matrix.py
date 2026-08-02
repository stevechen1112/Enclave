"""Validate that BookStack really enforces the ACL matrix we generated.

The matrix in acl_matrix.json is derived from the configuration we applied. Before
CV-PH-03 depends on it, we confirm the source system agrees: query BookStack as each
user with their own API token and compare the pages they can actually see.

A mismatch here means the fixture is wrong, and any downstream "ACL leakage = 0"
claim would be measuring against a fictional baseline.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
MATRIX = ROOT / "testdata" / "golden" / "acl_matrix.json"
ARTIFACT = ROOT / "artifacts" / "bookstack_acl_fixture_last_run.json"

BASE = os.getenv("BOOKSTACK_URL", "http://localhost:8090").rstrip("/")
DB_CONTAINER = os.getenv("BOOKSTACK_DB_CONTAINER", "bookstack-db")
APP_CONTAINER = os.getenv("BOOKSTACK_APP_CONTAINER", "bookstack")
DB_USER = os.getenv("BOOKSTACK_DB_USER", "bookstack")
DB_PASSWORD = os.getenv("BOOKSTACK_DB_PASSWORD", "bookstack_pw")
DB_NAME = os.getenv("BOOKSTACK_DB_NAME", "bookstackapp")


def docker(container: str, *args: str) -> str:
    result = subprocess.run(["docker", "exec", container, *args],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"docker exec {container} failed: {result.stderr[:300]}")
    return result.stdout


def bcrypt_hash(secret: str) -> str:
    out = docker(APP_CONTAINER, "php", "-r",
                 f"echo password_hash('{secret}', PASSWORD_BCRYPT);")
    return out.strip()


def mysql(sql: str) -> str:
    return docker(DB_CONTAINER, "mariadb", f"-u{DB_USER}", f"-p{DB_PASSWORD}", DB_NAME, "-e", sql)


def issue_token(email: str, token_id: str, secret: str) -> None:
    digest = bcrypt_hash(secret)
    mysql(
        f"DELETE FROM api_tokens WHERE token_id='{token_id}';"
        f"INSERT INTO api_tokens (name, token_id, secret, user_id, expires_at, created_at, updated_at) "
        f"SELECT 'enclave-acl-verify','{token_id}','{digest}', id, '2030-01-01', NOW(), NOW() "
        f"FROM users WHERE email='{email}' LIMIT 1;"
    )


def visible_page_ids(token_id: str, secret: str) -> set[int]:
    req = urllib.request.Request(
        f"{BASE}/api/pages?count=500",
        headers={"Authorization": f"Token {token_id}:{secret}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read()).get("data", [])
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"pages listing failed: HTTP {e.code} {e.read()[:200]}") from None
    return {int(p["id"]) for p in data}


def main() -> int:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    users = matrix["users"]

    observed: dict[str, set[int]] = {}
    for idx, (key, email) in enumerate(users.items()):
        token_id = f"enclaveverify{key}".ljust(32, "0")[:32]
        secret = f"enclavesecret{key}".ljust(32, "0")[:32]
        issue_token(email, token_id, secret)
        observed[key] = visible_page_ids(token_id, secret)
        print(f"{key:6s} ({email}) sees pages: {sorted(observed[key])}")

    rows, mismatches = [], []
    for entry in matrix["matrix"]:
        actual = entry["page_id"] in observed[entry["user"]]
        ok = actual == entry["expected_visible"]
        row = {**entry, "actual_visible": actual, "match": ok}
        rows.append(row)
        if not ok:
            mismatches.append(row)

    leaks = [r for r in mismatches if r["actual_visible"] and not r["expected_visible"]]
    missing = [r for r in mismatches if not r["actual_visible"] and r["expected_visible"]]

    report = {
        "gate": "BS-fixture-validation",
        "status": "PASS" if not mismatches else "FAIL",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "bookstack",
        "pairs": len(rows),
        "matches": sum(1 for r in rows if r["match"]),
        "leaks": len(leaks),
        "missing_access": len(missing),
        "note": "Confirms BookStack enforces the generated matrix; prerequisite for CV-PH-03.",
        "mismatches": mismatches,
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\npairs={report['pairs']} matches={report['matches']} "
          f"leaks={report['leaks']} missing={report['missing_access']}")
    for m in mismatches[:15]:
        print(f"  MISMATCH {m['user']}/{m['page']} expected={m['expected_visible']} "
              f"actual={m['actual_visible']} case={m['case']}")
    print(f"status = {report['status']}")
    print(f"written: {ARTIFACT}")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
