"""Kick Celery process_document_task for Z4 docs stuck in uploading."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUCK = ROOT / "artifacts" / "blind_z4" / "_stuck_ids.json"


def main() -> None:
    stuck = json.loads(STUCK.read_text(encoding="utf-8"))
    # Only re-queue uploading; parsing/embedding already mid-flight
    ids = [r["id"] for r in stuck if r.get("status") == "uploading"]
    print(f"kick uploading={len(ids)}")
    if not ids:
        return
    id_list = ",".join(f"'{i}'" for i in ids)
    sql = (
        "SELECT id::text || '|' || COALESCE(file_path,'') || '|' || tenant_id::text "
        f"FROM documents WHERE id IN ({id_list});"
    )
    out = subprocess.check_output(
        ["docker", "exec", "enclave-db-1", "psql", "-U", "postgres", "-d", "enclave", "-t", "-A", "-c", sql],
        text=True,
        encoding="utf-8",
    )
    rows = [ln.strip() for ln in out.splitlines() if ln.strip()]
    print(f"db rows={len(rows)}")
    py = [
        "from app.tasks.document_tasks import process_document_task",
    ]
    for ln in rows:
        did, fp, tid = ln.split("|", 2)
        if not fp:
            print(f"SKIP no path {did}")
            continue
        py.append(
            f"process_document_task.delay(document_id={did!r}, file_path={fp!r}, tenant_id={tid!r})"
        )
        py.append(f"print('queued', {did!r})")
    script = "\n".join(py)
    subprocess.check_call(
        ["docker", "exec", "-i", "enclave-worker-1", "python", "-c", script],
    )


if __name__ == "__main__":
    main()
