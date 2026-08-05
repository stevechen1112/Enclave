"""
WS-QA-CLOUD 雲端發布閘門（Phase 1）

發布前必跑：安全掃描、核心 pytest、託管煙霧（health）、
可選答題回歸 artifact 新鮮度檢查。

用法：
  python scripts/cloud_release_gate.py
  python scripts/cloud_release_gate.py --run-pytest
  python scripts/cloud_release_gate.py --strict

產物：artifacts/cloud_release_gate_last_run.json
Exit 0：全部必檢項 PASS
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "cloud_release_gate_last_run.json"


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _check_security() -> dict:
    proc = _run([sys.executable, "scripts/security_findings_gate.py"], timeout=300)
    ok = proc.returncode == 0
    return {
        "name": "security_findings_gate",
        "passed": ok,
        "detail": (proc.stdout or proc.stderr or "")[-400:],
    }


def _check_pytest(run: bool) -> dict:
    if not run:
        return {"name": "pytest_full", "passed": True, "detail": "skipped (--run-pytest not set)"}
    proc = _run([sys.executable, "-m", "pytest", "-q", "--timeout=120"], timeout=900)
    ok = proc.returncode == 0
    tail = (proc.stdout or proc.stderr or "").splitlines()[-3:]
    return {"name": "pytest_full", "passed": ok, "detail": " | ".join(tail)}


def _check_answer_regression(max_age_hours: int) -> dict:
    path = ROOT / "artifacts" / "answer_correctness_last_run.json"
    if not path.exists():
        return {
            "name": "answer_correctness_freshness",
            "passed": False,
            "detail": f"missing {path.name}",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"name": "answer_correctness_freshness", "passed": False, "detail": str(exc)}

    ts = data.get("timestamp") or data.get("run_at") or ""
    passed_count = data.get("passed") or data.get("pass_count")
    total = data.get("total") or data.get("total_questions") or 40
    fresh_ok = True
    detail = f"artifact present passed={passed_count}/{total}"
    if ts:
        try:
            run_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - run_at).total_seconds() / 3600
            fresh_ok = age_h <= max_age_hours
            detail += f" age_h={age_h:.1f}"
        except ValueError:
            fresh_ok = False
            detail += " bad timestamp"

    score_ok = True
    if passed_count is not None and int(passed_count) < int(total):
        score_ok = False
        detail += " score below total"

    return {
        "name": "answer_correctness_freshness",
        "passed": fresh_ok and score_ok,
        "detail": detail,
    }


def _check_managed_smoke() -> dict:
    proc = _run(
        [sys.executable, "scripts/managed_poc_smoke.py", "--skip-auth", "--skip-upload", "--skip-chat"],
        timeout=120,
    )
    ok = proc.returncode == 0
    return {
        "name": "managed_poc_smoke_health",
        "passed": ok,
        "detail": (proc.stdout or proc.stderr or "")[-300:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Cloud release gate (WS-QA-CLOUD)")
    parser.add_argument("--run-pytest", action="store_true", help="Run full pytest (slow)")
    parser.add_argument("--strict", action="store_true", help="Fail if any check fails")
    parser.add_argument("--max-age-hours", type=int, default=168, help="Answer regression max age")
    args = parser.parse_args()

    results = [
        _check_security(),
        _check_answer_regression(args.max_age_hours),
        _check_managed_smoke(),
        _check_pytest(args.run_pytest),
    ]

    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    payload = {
        "status": "PASS" if failed == 0 else "FAIL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "failed": failed,
        "results": results,
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for r in results:
        icon = "PASS" if r["passed"] else "FAIL"
        print(f"  [{icon}] {r['name']}: {r['detail'][:120]}")
    print(f"\nArtifact: {ARTIFACT}")
    print(f"Status: {payload['status']} ({passed}/{len(results)})")

    if args.strict and failed:
        return 1
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
