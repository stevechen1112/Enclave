from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _driver():
    return _load(ROOT / "scripts" / "p5_degradation_drivers" / "live_drill.py")


def _planner():
    return _load(ROOT / "scripts" / "prepare_p5_degradation_plans.py")


def test_container_lookup_is_scoped_to_exact_compose_labels(monkeypatch):
    module = _driver()
    captured = []

    def fake_run(argv, **_kwargs):
        captured.append(argv)
        return "container-id"

    monkeypatch.setattr(module, "_run", fake_run)
    assert module._container("enclave-p5", "worker") == "container-id"
    argv = captured[0]
    assert "label=com.docker.compose.project=enclave-p5" in argv
    assert "label=com.docker.compose.service=worker" in argv


def test_container_lookup_rejects_ambiguous_target(monkeypatch):
    module = _driver()
    monkeypatch.setattr(module, "_run", lambda *_args, **_kwargs: "one\ntwo")
    with pytest.raises(module.DrillError, match="exactly one"):
        module._container("enclave-p5", "worker")


def test_recovery_does_not_require_probe_artifacts(tmp_path):
    module = _driver()
    missing = tmp_path / "missing"
    args = SimpleNamespace(
        scenario="provider_slow",
        step="recover",
        source_commit="a" * 40,
        fixture=missing,
        credentials=missing,
        grounding_evidence=missing,
        integrity_script=missing,
        sidecar_key="ragflow",
    )
    module._validate_args(args)


def test_queue_recovery_removes_only_owned_markers_and_unpauses(monkeypatch, tmp_path):
    module = _driver()
    calls = []
    monkeypatch.setattr(module, "_container", lambda _project, service: service)
    monkeypatch.setattr(
        module,
        "_queue_remove",
        lambda container, marker: calls.append((container, marker))
        or {"removed": 5, "depth": 0},
    )
    monkeypatch.setattr(module, "_unpause", lambda container: calls.append(("unpause", container)))
    args = SimpleNamespace(
        scenario="queue_saturated",
        compose_project="enclave-p5",
        state_file=tmp_path / "state.json",
    )
    state = {
        "stage": "probed",
        "queue_marker": "owned-marker",
        "queue_markers": 5,
        "observations": [],
    }
    module._recover(args, state)
    assert calls == [("web", "owned-marker"), ("unpause", "worker")]
    assert state["stage"] == "recovered"


def test_queue_injection_journals_recovery_marker_before_fill(monkeypatch, tmp_path):
    module = _driver()
    monkeypatch.setattr(module, "_container", lambda _project, service: service)
    monkeypatch.setattr(module, "_queue_snapshot", lambda _web: {"depth": 0, "limit": 3})
    monkeypatch.setattr(module, "_pause", lambda _worker: None)
    monkeypatch.setattr(
        module,
        "_queue_fill",
        lambda *_args: (_ for _ in ()).throw(module.DrillError("interrupted fill")),
    )
    args = SimpleNamespace(
        scenario="queue_saturated",
        compose_project="enclave-p5",
        state_file=tmp_path / "state.json",
    )
    state = {"stage": "baseline", "observations": []}
    with pytest.raises(module.DrillError, match="interrupted fill"):
        module._inject(args, state)
    journal = module._read_state(args.state_file)
    assert journal["stage"] == "injecting"
    assert journal["queue_marker"].startswith("p5-degradation-marker:")
    assert journal["queue_markers_planned"] == 3


def test_plan_generator_emits_all_required_bound_steps(monkeypatch, tmp_path):
    module = _planner()
    monkeypatch.setattr(module, "_committed_hash", lambda *_args: "d" * 64)
    fixture = tmp_path / "fixture.md"
    credentials = tmp_path / "credentials.json"
    grounding = tmp_path / "grounding.json"
    for path in (fixture, credentials, grounding):
        path.write_text("{}", encoding="utf-8")
    environment = {
        "status": "PASS",
        "isolated_staging": True,
        "co_resident_enclave_projects": [],
        "source_commit": "a" * 40,
        "compose_project": "enclave-p5",
        "artifact_sha256": "e" * 64,
    }
    paths = module.build_plans(
        environment=environment,
        output_dir=tmp_path / "plans",
        python_executable=sys.executable,
        base_url="https://staging.example.test/",
        tenant_id="tenant-test",
        email="admin@example.test",
        fixture=fixture,
        credentials=credentials,
        grounding_evidence=grounding,
        provider_service="ollama-embed",
        sidecar_key="ragflow",
        sidecar_service="ragflow",
    )
    assert {path.stem.removesuffix(".plan") for path in paths} == {
        "provider_slow",
        "quota_exhausted",
        "queue_saturated",
        "sidecar_unavailable",
    }
    plan = module._object(paths[0])
    assert plan["source_commit"] == "a" * 40
    assert set(plan["commands"]) == {"baseline", "inject", "probe", "recover", "verify"}
    for step, command in plan["commands"].items():
        assert command["driver_sha256"] == "d" * 64
        assert command["trusted_files"] == [
            {
                "repo_path": "scripts/run_p5_integrity_probe.py",
                "sha256": "d" * 64,
            }
        ]
        assert command["argv"][-2:] == ["--p5-step", step]
        assert not any("password" in item.lower() for item in command["argv"])


def test_plan_generator_rejects_shared_host(monkeypatch, tmp_path):
    module = _planner()
    monkeypatch.setattr(module, "_committed_hash", lambda *_args: "d" * 64)
    environment = {
        "status": "HOLD",
        "isolated_staging": False,
        "co_resident_enclave_projects": ["enclave"],
        "source_commit": "a" * 40,
        "compose_project": "enclave-staging",
    }
    missing = tmp_path / "unused"
    with pytest.raises(ValueError, match="not isolated-staging PASS"):
        module.build_plans(
            environment=environment,
            output_dir=tmp_path,
            python_executable=sys.executable,
            base_url="https://staging.example.test",
            tenant_id="tenant-test",
            email="admin@example.test",
            fixture=missing,
            credentials=missing,
            grounding_evidence=missing,
            provider_service="ollama-embed",
            sidecar_key="ragflow",
            sidecar_service="ragflow",
        )


def test_verify_binds_recovery_to_live_integrity(monkeypatch, tmp_path):
    module = _driver()

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _path, **_kwargs):
            return httpx.Response(
                200,
                json={
                    "monthly_query_limit": 100,
                    "monthly_token_limit": 1000,
                    "monthly_cost_limit_usd": 50.0,
                },
                request=httpx.Request("GET", "https://example.test/quota"),
            )

    monkeypatch.setattr(module.httpx, "Client", Client)
    monkeypatch.setattr(module, "_assert_release", lambda *_args: {"release_id": "test"})
    monkeypatch.setattr(module, "_login", lambda *_args: {"Authorization": "Bearer redacted"})
    monkeypatch.setattr(
        module,
        "_run_integrity",
        lambda *_args: {
            "status": "PASS",
            "data_corruption": 0,
            "cross_tenant_leak": 0,
            "unrecoverable_backlog": 0,
            "observations": {"foreign_asset_http_status": 404},
        },
    )
    args = SimpleNamespace(
        scenario="quota_exhausted",
        source_commit="a" * 40,
        tenant_id="tenant-test",
        email="admin@example.test",
        base_url="https://example.test",
        state_file=tmp_path / "state.json",
    )
    state = {
        "stage": "recovered",
        "original_quota": {
            "monthly_query_limit": 100,
            "monthly_token_limit": 1000,
            "monthly_cost_limit_usd": 50.0,
        },
        "observations": ["fault_recovered"],
    }
    result = module._verify(args, state)
    assert result["recovered"] is True
    assert result["data_loss"] == 0
    assert result["false_completion"] == 0
    assert result["cross_tenant_leak"] == 0
    assert state["stage"] == "verified"
