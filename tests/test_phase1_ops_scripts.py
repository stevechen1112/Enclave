"""provision_managed_instance / payment e2e 腳本結構測試。"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_provision_env_contains_security_defaults():
    mod = _load("provision_managed", "scripts/provision_managed_instance.py")
    text = mod.build_env_content(customer="acme", plan="team", domain="acme.example.com")
    assert "CLAMAV_ENABLED=true" in text
    assert "STORAGE_BACKEND=s3" in text
    assert "SECRET_KEY=" in text
    assert "enclave-acme" in text


def test_provision_dry_run_cli():
    proc = subprocess.run(
        [sys.executable, "scripts/provision_managed_instance.py", "--customer", "dryrun1", "--dry-run"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert proc.returncode == 0
    assert "compose" in (proc.stdout + proc.stderr).lower() or "docker compose" in proc.stdout


def test_payment_e2e_script_runs():
    proc = subprocess.run(
        [sys.executable, "scripts/e2e_payment_newebpay.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    art = ROOT / "artifacts" / "payment_e2e_last_run.json"
    assert art.exists()
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["status"] == "PASS"
