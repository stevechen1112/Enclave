"""Z0-5: remove repeated uploads from the production RAGFlow dataset.

Duplicate uploads distort every coverage statistic (the "39 zero-chunk documents"
in the original baseline turned out to be one scanned PDF uploaded 38 times), so the
dataset must be deduplicated before any parsing metric is quoted.

Safety: dry-run by default, writes a full inventory first, and refuses to delete any
RAGFlow document that an Enclave document still references.

Usage:
  python scripts/dedupe_ragflow_dataset.py            # report only
  python scripts/dedupe_ragflow_dataset.py --apply    # actually delete
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "ragflow_dedupe_last_run.json"

BASE = os.getenv("RAGFLOW_BASE_URL", "http://localhost:9380").rstrip("/")
KEY = os.getenv("RAGFLOW_API_KEY", "")
DATASET = os.getenv("RAGFLOW_DATASET_ID", "")


def api(method: str, path: str, payload=None):
    headers = {"Authorization": f"Bearer {KEY}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        return {"code": e.code, "message": e.read().decode(errors="replace")}


# RAGFlow appends "(1)", "(2)" ... when the same filename is uploaded again, so the
# stem plus size plus type identifies repeat uploads of one source document.
_COPY_SUFFIX = re.compile(r"\((\d+)\)(?=\.[^.]+$|$)")


def base_stem(name: str) -> str:
    return _COPY_SUFFIX.sub("", name)


def list_documents() -> list[dict]:
    docs, page = [], 1
    while True:
        got = api("GET", f"/api/v1/datasets/{DATASET}/documents?page={page}&page_size=100")
        batch = ((got.get("data") or {}).get("docs") or [])
        if not batch:
            break
        docs.extend(batch)
        page += 1
    return docs


def referenced_doc_ids() -> tuple[set[str], str]:
    """RAGFlow document ids that Enclave still points at, so we never orphan a citation."""
    try:
        from sqlalchemy import create_engine, text as sql_text
    except ImportError:
        return set(), "sqlalchemy unavailable"

    host, db, user = os.getenv("POSTGRES_SERVER"), os.getenv("POSTGRES_DB"), os.getenv("POSTGRES_USER")
    if not (host and db and user):
        return set(), "no database settings"
    url = (f"postgresql://{user}:{os.getenv('POSTGRES_PASSWORD', '')}"
           f"@{host}:{os.getenv('POSTGRES_PORT', '5432')}/{db}")
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            rows = conn.execute(sql_text(
                "SELECT quality_report FROM documents WHERE quality_report IS NOT NULL"
            )).fetchall()
            # The gateway registry is the authoritative projection record; a document
            # referenced only here (outbox/registry path) must still be protected.
            gw_rows = conn.execute(sql_text(
                "SELECT provider_resource_id FROM gateway_resources "
                "WHERE provider = 'ragflow' AND tombstoned_at IS NULL "
                "AND provider_resource_id IS NOT NULL"
            )).fetchall()
    except Exception as exc:
        return set(), f"db unreachable: {type(exc).__name__}"

    ids: set[str] = set()
    for (report,) in rows:
        if isinstance(report, str):
            try:
                report = json.loads(report)
            except json.JSONDecodeError:
                continue
        if isinstance(report, dict):
            ids.update(str(x) for x in (report.get("ragflow_doc_ids") or []))
    ids.update(str(r[0]) for r in gw_rows)
    return ids, f"ok (quality_report + {len(gw_rows)} gateway_resources)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not DATASET:
        print("RAGFLOW_DATASET_ID unset")
        return 2

    docs = list_documents()
    print(f"dataset {DATASET}: {len(docs)} documents")

    protected, db_status = referenced_doc_ids()
    print(f"enclave-referenced ragflow doc ids: {len(protected)} ({db_status})")

    groups: dict[tuple, list[dict]] = {}
    for d in docs:
        groups.setdefault((base_stem(d.get("name") or ""), d.get("size"), d.get("type")), []).append(d)

    keep, delete, blocked = [], [], []
    for (stem, size, _type), members in groups.items():
        # Keep a copy Enclave already cites; otherwise the copy with the most chunks.
        members.sort(key=lambda d: (d["id"] not in protected, -(d.get("chunk_count") or 0),
                                    str(d.get("create_time") or "")))
        keeper = members[0]
        keep.append({"id": keeper["id"], "name": keeper.get("name"), "stem": stem, "size": size,
                     "chunk_count": keeper.get("chunk_count") or 0, "copies": len(members),
                     "referenced": keeper["id"] in protected})
        for extra in members[1:]:
            row = {"id": extra["id"], "name": extra.get("name"), "stem": stem, "size": size,
                   "chunk_count": extra.get("chunk_count") or 0}
            (blocked if extra["id"] in protected else delete).append(row)

    report = {
        "task": "Z0-5",
        "mode": "apply" if args.apply else "dry_run",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dataset_id": DATASET,
        "documents_before": len(docs),
        "unique_documents": len(groups),
        "duplicates_removable": len(delete),
        "duplicates_blocked_by_reference": len(blocked),
        "enclave_reference_lookup": db_status,
        "keep": keep,
        "delete": delete,
        "blocked": blocked,
    }

    print(f"unique={len(groups)} removable_duplicates={len(delete)} blocked={len(blocked)}")
    for row in sorted(keep, key=lambda r: -r["copies"]):
        if row["copies"] > 1:
            print(f"  {row['copies']:3d}x  chunks={row['chunk_count']:4d}  size={row['size']:>9}  "
                  f"{str(row['name'])[:60]}")

    if args.apply and delete:
        ids = [row["id"] for row in delete]
        for i in range(0, len(ids), 50):
            resp = api("DELETE", f"/api/v1/datasets/{DATASET}/documents", {"ids": ids[i:i + 50]})
            print(f"  deleted batch {i // 50 + 1}: {resp.get('code', 'ok')}")
        after = list_documents()
        report["documents_after"] = len(after)
        print(f"documents after = {len(after)}")
    elif not args.apply:
        print("dry run; re-run with --apply to delete")

    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {ARTIFACT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
