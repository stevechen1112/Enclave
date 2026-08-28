from __future__ import annotations

import hashlib
import importlib.util
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


SOURCE_COMMIT = "a" * 40
COMPOSE_PROJECT = "enclave-p5-dedicated"


def _environment() -> dict:
    return {
        "status": "PASS",
        "execution_class": "live",
        "isolated_staging": True,
        "co_resident_enclave_projects": [],
        "source_commit": SOURCE_COMMIT,
        "compose_project": COMPOSE_PROJECT,
        "artifact_sha256": "e" * 64,
        "runtime_images": {
            "web": {
                "container": "enclave-p5-web-1",
                "container_id": "web-container-id",
                "image_id": "sha256:" + "b" * 64,
            }
        },
    }


def _driver_plan(
    module, tmp_path: Path, scenario: str, *, probe_exit: int = 0, false_completion: int = 0
) -> dict:
    module.ROOT = tmp_path
    driver_dir = tmp_path / "scripts" / "p5_degradation_drivers"
    driver_dir.mkdir(parents=True, exist_ok=True)
    driver = driver_dir / "test_driver.py"
    integrity = tmp_path / "scripts" / "run_p5_integrity_probe.py"
    integrity.write_text("# trusted test integrity probe\n", encoding="utf-8")
    driver.write_text(
        """import argparse, json
p=argparse.ArgumentParser()
p.add_argument('--p5-scenario', required=True)
p.add_argument('--p5-step', required=True)
p.add_argument('--source-commit', required=True)
p.add_argument('--compose-project', required=True)
p.add_argument('--tenant-id', required=True)
p.add_argument('--probe-exit', type=int, default=0)
p.add_argument('--false-completion', type=int, default=0)
p.add_argument('--integrity-script', required=True)
a=p.parse_args()
if a.p5_step == 'verify':
 print(json.dumps({'schema_version':1,'scenario':a.p5_scenario,
 'source_commit':a.source_commit,'tenant_id':'tenant-test',
 'data_loss':0,'false_completion':a.false_completion,
 'cross_tenant_leak':0,'recovered':True,
 'observations':['baseline','degraded','recovered']}))
raise SystemExit(a.probe_exit if a.p5_step == 'probe' else 0)
""",
        encoding="utf-8",
    )
    digest = hashlib.sha256(driver.read_bytes()).hexdigest()
    module._committed_driver_sha256 = lambda _driver, _commit: digest
    commands = {}
    for step in ("baseline", "inject", "probe", "recover", "verify"):
        argv = [
            sys.executable,
            str(driver),
            "--p5-scenario",
            scenario,
            "--p5-step",
            step,
            "--source-commit",
            SOURCE_COMMIT,
            "--compose-project",
            COMPOSE_PROJECT,
            "--tenant-id",
            "tenant-test",
            "--integrity-script",
            str(integrity),
        ]
        if step == "probe":
            argv += ["--probe-exit", str(probe_exit)]
        if step == "verify":
            argv += ["--false-completion", str(false_completion)]
        commands[step] = {
            "argv": argv,
            "driver": "scripts/p5_degradation_drivers/test_driver.py",
            "driver_sha256": digest,
            "trusted_files": [
                {
                    "repo_path": "scripts/run_p5_integrity_probe.py",
                    "sha256": digest,
                }
            ],
        }
    return {
        "schema_version": 1,
        "scenario": scenario,
        "source_commit": SOURCE_COMMIT,
        "compose_project": COMPOSE_PROJECT,
        "tenant_id": "tenant-test",
        "environment_artifact_sha256": "e" * 64,
        "commands": commands,
    }


def test_degradation_runner_requires_live_integrity_payload(tmp_path):
    module = _load_script("run_p5_degradation.py")
    plan = _driver_plan(module, tmp_path, "provider_slow")
    report, transcript = module.execute_plan(
        plan, timeout=5, environment=_environment()
    )
    assert report["status"] == "PASS"
    assert transcript["steps"]["recover"]["exit_code"] == 0

    plan = _driver_plan(
        module, tmp_path, "provider_slow", false_completion=1
    )
    failed, _ = module.execute_plan(plan, timeout=5, environment=_environment())
    assert failed["status"] == "FAIL"


def test_degradation_runner_always_attempts_recovery_after_failed_probe(tmp_path):
    module = _load_script("run_p5_degradation.py")
    plan = _driver_plan(module, tmp_path, "queue_saturated", probe_exit=3)
    report, transcript = module.execute_plan(
        plan, timeout=5, environment=_environment()
    )
    assert report["status"] == "FAIL"
    assert transcript["steps"]["recover"]["exit_code"] == 0


def test_degradation_runner_rejects_unknown_scenario():
    module = _load_script("run_p5_degradation.py")
    with pytest.raises(ValueError, match="unsupported"):
        module.execute_plan(
            {"schema_version": 1, "scenario": "made_up"},
            timeout=5,
            environment=_environment(),
        )


def test_degradation_runner_rejects_arbitrary_inline_commands(tmp_path):
    module = _load_script("run_p5_degradation.py")
    plan = _driver_plan(module, tmp_path, "provider_slow")
    trusted = plan["commands"]["baseline"]["trusted_files"]
    integrity = tmp_path / "scripts" / "run_p5_integrity_probe.py"
    plan["commands"]["probe"] = {
        "argv": [
            sys.executable,
            "-c",
            "print('fake pass')",
            "--integrity-script",
            str(integrity),
        ],
        "driver": "scripts/p5_degradation_drivers/test_driver.py",
        "driver_sha256": plan["commands"]["baseline"]["driver_sha256"],
        "trusted_files": trusted,
    }
    with pytest.raises(ValueError, match="execute its pinned driver"):
        module.execute_plan(plan, timeout=5, environment=_environment())


def test_degradation_runner_rejects_non_isolated_environment(tmp_path):
    module = _load_script("run_p5_degradation.py")
    plan = _driver_plan(module, tmp_path, "provider_slow")
    environment = _environment()
    environment["status"] = "HOLD"
    environment["isolated_staging"] = False
    with pytest.raises(ValueError, match="not PASS"):
        module.execute_plan(plan, timeout=5, environment=environment)


def test_degradation_runner_rejects_sensitive_argv(tmp_path):
    module = _load_script("run_p5_degradation.py")
    plan = _driver_plan(module, tmp_path, "provider_slow")
    plan["commands"]["probe"]["argv"] += ["--api-token", "must-not-leak"]
    with pytest.raises(ValueError, match="sensitive flag"):
        module.execute_plan(plan, timeout=5, environment=_environment())


def test_degradation_runner_rejects_driver_from_another_commit(tmp_path):
    module = _load_script("run_p5_degradation.py")
    plan = _driver_plan(module, tmp_path, "provider_slow")
    module._committed_driver_sha256 = lambda _driver, _commit: "f" * 64
    with pytest.raises(ValueError, match="does not match source_commit"):
        module.execute_plan(plan, timeout=5, environment=_environment())


def test_degradation_runner_requires_committed_integrity_probe(tmp_path):
    module = _load_script("run_p5_degradation.py")
    plan = _driver_plan(module, tmp_path, "provider_slow")
    plan["commands"]["verify"]["trusted_files"] = []
    with pytest.raises(ValueError, match="trusted_files"):
        module.execute_plan(plan, timeout=5, environment=_environment())


def test_degradation_runner_rejects_integrity_probe_hash_mismatch(tmp_path):
    module = _load_script("run_p5_degradation.py")
    plan = _driver_plan(module, tmp_path, "provider_slow")
    plan["commands"]["verify"]["trusted_files"][0]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="does not match source_commit"):
        module.execute_plan(plan, timeout=5, environment=_environment())


def test_degradation_runner_rejects_tenant_or_environment_plan_tampering(tmp_path):
    module = _load_script("run_p5_degradation.py")
    plan = _driver_plan(module, tmp_path, "provider_slow")
    plan["tenant_id"] = "other-tenant"
    with pytest.raises(ValueError, match="invalid --tenant-id"):
        module.execute_plan(plan, timeout=5, environment=_environment())

    plan = _driver_plan(module, tmp_path, "provider_slow")
    plan["environment_artifact_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="environment artifact mismatch"):
        module.execute_plan(plan, timeout=5, environment=_environment())

    plan = _driver_plan(module, tmp_path, "provider_slow")
    plan["commands"]["probe"]["argv"] += ["--tenant-id", "other-tenant"]
    with pytest.raises(ValueError, match="exactly one --tenant-id"):
        module.execute_plan(plan, timeout=5, environment=_environment())


def test_assembler_uses_authoritative_spec_and_does_not_claim_pass():
    module = _load_script("assemble_p5_evidence.py")
    evidence = module.assemble_evidence(
        capacity_reports=[],
        soak_report={"status": "NOT_RUN"},
        cost_report={"status": "NOT_RUN"},
        degradation_reports=[],
        environments=[
            {
                "isolated_staging": False,
                "source_commit": "a" * 40,
                "runtime_images": {"web": {"image_id": "sha256:abc"}},
            }
        ],
        operator="test",
    )
    assert evidence["capacity_spec_sha256"]
    assert evidence["capacity_spec_sha256"] == module.capacity_spec_sha256(
        load_capacity_spec()
    )
    assert module.evaluate_p5_capacity_evidence(evidence)["status"] == "HOLD"
    assert evidence["environments"][0]["isolated_staging"] is False
