from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.services.capacity_gate import load_capacity_spec

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _python_command(output: str, exit_code: int = 0) -> list[str]:
    return [
        sys.executable,
        "-c",
        f"import sys; print({output!r}); raise SystemExit({exit_code})",
    ]


def test_degradation_runner_requires_live_integrity_payload():
    module = _load_script("run_p5_degradation.py")
    ok = _python_command("ok")
    plan = {
        "scenario": "provider_slow",
        "commands": {
            "baseline": ok,
            "inject": ok,
            "probe": ok,
            "recover": ok,
            "verify": _python_command(
                json.dumps({"data_loss": 0, "false_completion": 0})
            ),
        },
    }
    report, transcript = module.execute_plan(plan, timeout=5)
    assert report["status"] == "PASS"
    assert transcript["steps"]["recover"]["exit_code"] == 0

    plan["commands"]["verify"] = _python_command(
        json.dumps({"data_loss": 0, "false_completion": 1})
    )
    failed, _ = module.execute_plan(plan, timeout=5)
    assert failed["status"] == "FAIL"


def test_degradation_runner_always_attempts_recovery_after_failed_probe():
    module = _load_script("run_p5_degradation.py")
    ok = _python_command("ok")
    plan = {
        "scenario": "queue_saturated",
        "commands": {
            "baseline": ok,
            "inject": ok,
            "probe": _python_command("failed", 3),
            "recover": ok,
            "verify": _python_command(
                json.dumps({"data_loss": 0, "false_completion": 0})
            ),
        },
    }
    report, transcript = module.execute_plan(plan, timeout=5)
    assert report["status"] == "FAIL"
    assert transcript["steps"]["recover"]["exit_code"] == 0


def test_degradation_runner_rejects_unknown_scenario():
    module = _load_script("run_p5_degradation.py")
    with pytest.raises(ValueError, match="unsupported"):
        module.execute_plan({"scenario": "made_up"}, timeout=5)


def test_assembler_uses_authoritative_spec_and_does_not_claim_pass():
    module = _load_script("assemble_p5_evidence.py")
    evidence = module.assemble_evidence(
        capacity_reports=[],
        soak_report={"status": "NOT_RUN"},
        cost_report={"status": "NOT_RUN"},
        degradation_reports=[],
        source_commit="a" * 40,
        runtime_images={"web": "sha256:abc"},
        operator="test",
    )
    assert evidence["capacity_spec_sha256"]
    assert evidence["capacity_spec_sha256"] == module.capacity_spec_sha256(
        load_capacity_spec()
    )
    assert module.evaluate_p5_capacity_evidence(evidence)["status"] == "HOLD"
