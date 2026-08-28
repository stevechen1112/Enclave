from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tests" / "load" / "capacity_config.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("p5_capacity_config", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_target_comes_from_capacity_spec(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("CAPACITY_PROFILE", "lite")
    monkeypatch.setenv("LOAD_MULTIPLIER", "2")
    assert module.target_load()["concurrent_users"] == 40
    assert len(module.spec_sha256()) == 64


def test_load_multiplier_cannot_understate_p5_target(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("CAPACITY_PROFILE", "standard")
    monkeypatch.setenv("LOAD_MULTIPLIER", "1.5")
    with pytest.raises(ValueError, match="below"):
        module.target_load()


def test_soak_load_allows_exact_peak_but_not_below(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("CAPACITY_PROFILE", "lite")
    monkeypatch.setenv("LOAD_TEST_CLASS", "soak")
    monkeypatch.setenv("LOAD_MULTIPLIER", "1")
    assert module.target_load()["concurrent_users"] == 20

    monkeypatch.setenv("LOAD_MULTIPLIER", "0.5")
    with pytest.raises(ValueError, match="below"):
        module.target_load()


def test_full_scenario_requires_credentials_and_media_fixtures(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("P5_FULL_SCENARIO", "true")
    for name in (
        "LOAD_TEST_USER_PASSWORD",
        "LOAD_TEST_ADMIN_PASSWORD",
        "LOAD_TEST_SUPERUSER_PASSWORD",
        "LOAD_DOCUMENT_FIXTURE_PATH",
        "LOAD_AUDIO_FIXTURE_PATH",
        "LOAD_VIDEO_FIXTURE_PATH",
        "LOAD_TEST_CREDENTIALS_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    errors = module.validate_full_scenario_environment()
    assert len(errors) == 7
    assert any("VIDEO_FIXTURE" in error for error in errors)


def test_full_scenario_accepts_one_credential_per_virtual_user(monkeypatch, tmp_path):
    module = _load_module()
    for kind in ("document", "audio", "video"):
        path = tmp_path / f"{kind}.bin"
        path.write_bytes(b"fixture")
        monkeypatch.setenv(f"LOAD_{kind.upper()}_FIXTURE_PATH", str(path))
    credentials = [
        {"email": f"load-{index}@example.invalid", "password": "secret"}
        for index in range(40)
    ]
    credential_path = tmp_path / "credentials.json"
    credential_path.write_text(json.dumps(credentials), encoding="utf-8")
    monkeypatch.setenv("LOAD_TEST_CREDENTIALS_PATH", str(credential_path))
    monkeypatch.setenv("CAPACITY_PROFILE", "lite")
    monkeypatch.setenv("LOAD_MULTIPLIER", "2")
    monkeypatch.setenv("P5_FULL_SCENARIO", "true")
    for name in (
        "LOAD_TEST_USER_PASSWORD",
        "LOAD_TEST_ADMIN_PASSWORD",
        "LOAD_TEST_SUPERUSER_PASSWORD",
    ):
        monkeypatch.setenv(name, "injected")
    assert module.validate_full_scenario_environment() == []
    assert len(module.credential_pool()) == 40


def test_locust_contract_uses_current_api_routes():
    source = (ROOT / "tests" / "load" / "locustfile.py").read_text(encoding="utf-8")
    for route in (
        "/api/v1/auth/login/access-token",
        "/api/v1/knowledge/assets",
        "/api/v1/kb/search",
        "/api/v1/chat/chat",
    ):
        assert route in source
    assert '/api/v1/auth/login"' not in source
    assert '/api/v1/chat/"' not in source
