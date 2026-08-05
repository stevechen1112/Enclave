"""Clear duplicate chunks and requeue Z4 docs stuck in parsing/embedding."""
from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
UP = ROOT / "artifacts" / "blind_z4" / "upload_result.json"
BASE = "http://localhost:8011"
STUCK_STATUSES = {"uploading", "parsing", "embedding", "uploaded", "pending"}


def api_stuck() -> list[dict]:
    up = json.loads(UP.read_text(encoding="utf-8"))["uploaded"]
    want = {r["id"]: r["name"] for r in up if r.get("ok")}
    c = httpx.Client(base_url=BASE, timeout=60)
    r = c.post(
        "/api/v1/auth/login/access-token",
        data={"username": "admin@enclave.local", "password": "admin123"},
    )
    r.raise_for_status()
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    items = c.get("/api/v1/documents/", params={"limit": 400}).json()
    items = items if isinstance(items, list) else (items.get("items") or items.get("data") or [])
    by_id = {d["id"]: d for d in items}
    out = []
    for did, name in want.items():
        d = by_id.get(did) or {}
        st = d.get("status") or "MISSING"
        if st in STUCK_STATUSES or st == "failed":
            out.append({"id": did, "name": name, "status": st})
    return out


def main() -> None:
    stuck = api_stuck()
    print("stuck", Counter(r["status"] for r in stuck), "n=", len(stuck))
    if not stuck:
        return
    ids = ",".join(f"'{r['id']}'" for r in stuck)
    # Count existing chunks; if chunks exist with embeddings, force completed
    sql_info = f"""
SELECT d.id::text, d.status, d.file_path, d.tenant_id::text,
       COALESCE(c.n,0) AS chunks,
       COALESCE(c.emb,0) AS with_emb
FROM documents d
LEFT JOIN (
  SELECT document_id, count(*) n,
         count(*) FILTER (WHERE embedding IS NOT NULL) emb
  FROM documentchunks GROUP BY document_id
) c ON c.document_id = d.id
WHERE d.id IN ({ids});
"""
    info = subprocess.check_output(
        ["docker", "exec", "enclave-db-1", "psql", "-U", "postgres", "-d", "enclave", "-t", "-A", "-F", "|", "-c", sql_info],
        text=True,
        encoding="utf-8",
    )
    force_ids = []
    requeue = []
    for ln in info.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        did, status, fp, tid, n, emb = ln.split("|")
        n_i, emb_i = int(n), int(emb)
        print(f"  {status} chunks={n_i} emb={emb_i} {did[:8]}…")
        if n_i > 0 and emb_i >= n_i:
            force_ids.append(did)
        else:
            requeue.append((did, fp, tid, n_i))

    if force_ids:
        id_list = ",".join(f"'{i}'" for i in force_ids)
        subprocess.check_call(
            [
                "docker",
                "exec",
                "enclave-db-1",
                "psql",
                "-U",
                "postgres",
                "-d",
                "enclave",
                "-c",
                f"UPDATE documents SET status='completed', error_message=NULL WHERE id IN ({id_list});",
            ]
        )
        print("forced completed", len(force_ids))

    if requeue:
        # delete partial chunks then requeue
        id_list = ",".join(f"'{i}'" for i, *_ in requeue)
        subprocess.check_call(
            [
                "docker",
                "exec",
                "enclave-db-1",
                "psql",
                "-U",
                "postgres",
                "-d",
                "enclave",
                "-c",
                f"DELETE FROM documentchunks WHERE document_id IN ({id_list}); "
                f"UPDATE documents SET status='pending', error_message=NULL WHERE id IN ({id_list});",
            ]
        )
        py = ["from app.tasks.document_tasks import process_document_task"]
        for did, fp, tid, _ in requeue:
            if not fp:
                print("SKIP no path", did)
                continue
            py.append(
                f"process_document_task.delay(document_id={did!r}, file_path={fp!r}, tenant_id={tid!r})"
            )
            py.append(f"print('queued', {did!r})")
        subprocess.check_call(
            ["docker", "exec", "-i", "enclave-worker-1", "python", "-c", "\n".join(py)]
        )
        print("requeued", len(requeue))


if __name__ == "__main__":
    main()
