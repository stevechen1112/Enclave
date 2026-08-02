"""N-1 upgrade dry-run: alembic current → upgrade head → optional downgrade -1.
Writes artifacts/ops/n1_upgrade_*.json. On-site sign-off remains human.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "artifacts" / "ops"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)


def main() -> int:
    dry = "--execute" not in sys.argv
    steps = []
    ok = True

    cur = _run([sys.executable, "-m", "alembic", "current"])
    steps.append({"step": "current", "rc": cur.returncode, "out": (cur.stdout or "")[-500:]})
    if cur.returncode != 0:
        ok = False

    if dry:
        steps.append({
            "step": "dry_run",
            "note": "Pass --execute to run alembic upgrade head && downgrade -1",
            "planned": ["alembic upgrade head", "alembic downgrade -1", "alembic upgrade head"],
        })
    else:
        for label, args in [
            ("upgrade_head", ["upgrade", "head"]),
            ("downgrade_n1", ["downgrade", "-1"]),
            ("reupgrade_head", ["upgrade", "head"]),
        ]:
            proc = _run([sys.executable, "-m", "alembic", *args])
            steps.append({
                "step": label,
                "rc": proc.returncode,
                "stderr": (proc.stderr or "")[-800:],
            })
            if proc.returncode != 0:
                ok = False
                break

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "action": "n1_upgrade",
        "dry_run": dry,
        "status": "ok" if ok else "error",
        "steps": steps,
        "human_gate": "on-site DR/sign-off still required",
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / f"n1_upgrade_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("log=", path)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
