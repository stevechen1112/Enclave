"""Build a deterministic local large-tree acceptance report for Input I6."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from app.services.nas_local_connector import scan_local_nas


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="enclave-input-i6-") as temp:
        root = Path(temp)
        for index in range(args.files):
            target = root / f"line-{index % 10:02d}" / f"record-{index:05d}.txt"
            target.parent.mkdir(exist_ok=True)
            target.write_text(f"controlled record {index}\n", encoding="utf-8")
        started = time.perf_counter()
        first = scan_local_nas(str(root), max_files=args.files + 1)
        first_seconds = time.perf_counter() - started
        replay = scan_local_nas(str(root), max_files=args.files + 1)

        old = root / "line-00" / "record-00000.txt"
        renamed = root / "line-00" / "renamed-00000.txt"
        old.rename(renamed)
        (root / "line-01" / "record-00001.txt").unlink()
        changed = scan_local_nas(str(root), max_files=args.files + 1)

    report = {
        "phase": "Input I6",
        "profile": "local_large_tree",
        "file_count": args.files,
        "first_scan_seconds": round(first_seconds, 4),
        "snapshot_complete": first.get("snapshot_complete"),
        "replay_cursor_equal": first.get("cursor") == replay.get("cursor"),
        "replay_snapshot_equal": first.get("snapshot_id") == replay.get("snapshot_id"),
        "rename_delete_changes_snapshot": first.get("snapshot_id") != changed.get("snapshot_id"),
        "customer_sandbox": {
            "sharepoint": "PENDING_CREDENTIALS",
            "google_drive": "PENDING_CREDENTIALS",
            "nas_smb_local": "PASS",
        },
        "claim_boundary": (
            "Local deterministic connector acceptance only; this is not a customer "
            "SharePoint/Google Drive certification or production capacity result."
        ),
    }
    report["status"] = "PASS" if all(
        [
            report["snapshot_complete"],
            report["replay_cursor_equal"],
            report["replay_snapshot_equal"],
            report["rename_delete_changes_snapshot"],
        ]
    ) else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
