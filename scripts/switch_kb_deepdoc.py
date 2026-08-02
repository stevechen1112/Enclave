"""B1 — switch the production RAGFlow KB to DeepDOC layout recognition.

The production KB was created with ``layout_recognize=Plain Text``, which is the
root cause of the CV-INT FAIL: 7 documents carry a ``ragflow/deepdoc`` label that
the upstream dataset config does not back. This script flips the dataset's
``parser_config.layout_recognize`` to ``DeepDOC`` so future (re)parses genuinely
run the DeepDOC pipeline.

It only changes the dataset config. Existing chunks are NOT re-parsed here — that
is B2's job. Run with ``--apply`` to actually write; default is a dry run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "kb_deepdoc_switch.json"


def _load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write the change")
    ap.add_argument("--dataset-id", default=None, help="override RAGFLOW_DATASET_ID")
    args = ap.parse_args()

    _load_env()
    base = os.environ.get("RAGFLOW_BASE_URL", "http://localhost:9380").rstrip("/")
    key = os.environ.get("RAGFLOW_API_KEY", "")
    dsid = args.dataset_id or os.environ.get("RAGFLOW_DATASET_ID", "")
    if not (key and dsid):
        print("RAGFLOW_API_KEY / RAGFLOW_DATASET_ID required")
        return 1
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    with httpx.Client(timeout=30) as client:
        # Read current config (paginate in case the dataset is not on page 1).
        current = None
        page = 1
        while True:
            r = client.get(f"{base}/api/v1/datasets?page={page}&page_size=100", headers=headers)
            r.raise_for_status()
            batch = r.json().get("data") or []
            if not batch:
                break
            for ds in batch:
                if ds.get("id") == dsid:
                    current = ds
                    break
            if current:
                break
            page += 1
        if not current:
            print(f"dataset {dsid} not found")
            return 1

        pc = current.get("parser_config") or {}
        before = pc.get("layout_recognize")
        print(f"dataset: {current.get('name')} ({dsid})")
        print(f"current layout_recognize: {before!r}")

        if before == "DeepDOC":
            print("already DeepDOC; nothing to do")
            return 0

        # Only send the field being changed. Echoing the full parser_config back
        # fails validation because the read model carries read-only/computed keys
        # (children_delimiter, image_context_size, llm_id, ...) that the update
        # schema rejects as "Extra inputs are not permitted".
        payload = {"parser_config": {"layout_recognize": "DeepDOC"}}

        record = {
            "dataset_id": dsid,
            "dataset_name": current.get("name"),
            "before": before,
            "after": "DeepDOC",
            "applied": bool(args.apply),
        }

        if not args.apply:
            print("DRY RUN — would set layout_recognize=DeepDOC. Re-run with --apply.")
            ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
            ARTIFACT.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0

        u = client.put(f"{base}/api/v1/datasets/{dsid}", headers=headers, json=payload)
        if u.status_code != 200 or (u.json().get("code") not in (0, None)):
            print(f"update failed: {u.status_code} {u.text[:300]}")
            return 1

        # Verify
        v = client.get(f"{base}/api/v1/datasets?id={dsid}", headers=headers)
        data = v.json().get("data")
        if isinstance(data, list) and data:
            data = data[0]
        after = (data.get("parser_config") or {}).get("layout_recognize")
        record["verified_after"] = after
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"verified layout_recognize: {after!r}")
        if after != "DeepDOC":
            print("WARNING: value did not persist as DeepDOC")
            return 1
        print("OK — production KB now uses DeepDOC. Existing chunks unchanged (see B2).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
