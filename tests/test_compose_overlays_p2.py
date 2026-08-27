"""P2: compose overlays, image pins, deploy order, mobile experimental."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "compose"


def test_compose_overlay_files_exist():
    assert (COMPOSE / "sidecars.yml").is_file()
    assert (COMPOSE / "enterprise.yml").is_file()
    assert (COMPOSE / "image-pins.env").is_file()
    assert (COMPOSE / "pack-enabled.env").is_file()
    assert (COMPOSE / "README.md").is_file()


def test_profiles_includes_overlays():
    text = (ROOT / "docker-compose.profiles.yml").read_text(encoding="utf-8")
    assert "compose/sidecars.yml" in text
    assert "compose/enterprise.yml" in text
    assert "path: compose/sidecars.yml" in text


def test_sidecar_images_not_latest():
    """Third-party sidecar/enterprise images must not default to :latest."""
    for name in ("sidecars.yml", "enterprise.yml", "image-pins.env"):
        text = (COMPOSE / name).read_text(encoding="utf-8")
        # Allow comments mentioning latest; forbid image defaults ending with :latest
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert ":latest" not in stripped, f"{name}: bare latest in {stripped}"


def test_pipeshub_and_weknora_pinned_with_digest():
    pins = (COMPOSE / "image-pins.env").read_text(encoding="utf-8")
    assert "PIPESHUB_IMAGE=" in pins and "@sha256:" in pins
    assert "WEKNORA_IMAGE=" in pins and "v0.7.1@sha256:" in pins
    side = (COMPOSE / "sidecars.yml").read_text(encoding="utf-8")
    assert "0.4.5@sha256:" in side
    assert "v0.7.1@sha256:" in side


def test_pack_enabled_env_turns_modules_on():
    text = (COMPOSE / "pack-enabled.env").read_text(encoding="utf-8")
    assert "RAGFLOW_ENABLED=true" in text
    assert "PIPESHUB_ENABLED=true" in text
    assert "WEKNORA_ENABLED=true" in text


def test_staging_and_prod_migrate_before_up():
    for wf in ("deploy-production.yml", "deploy-staging.yml"):
        text = (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
        stop_idx = text.find("stop web worker worker-beat")
        run_idx = text.find("run --rm -T migrate")
        provision_idx = text.find("run --rm -T provision-db-roles")
        up_idx = text.find("up -d --no-build --remove-orphans")
        assert all(
            index != -1 for index in (stop_idx, run_idx, provision_idx, up_idx)
        ), wf
        assert stop_idx < run_idx < provision_idx < up_idx, (
            f"{wf}: stop → migrate → provision → up"
        )


def test_database_credentials_are_split_by_runtime_identity():
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    web = compose.split("  web:", 1)[1].split("  db:", 1)[0]
    migrate = compose.split("  migrate:", 1)[1].split("  provision-db-roles:", 1)[0]
    provision = compose.split("  provision-db-roles:", 1)[1].split("  redis:", 1)[0]
    worker = compose.split("  worker:", 1)[1].split("  worker-beat:", 1)[0]

    assert ".env.production" in web
    assert ".env.db-admin" not in web
    assert ".env.maintenance" not in web
    assert ".env.db-admin" in migrate
    assert ".env.db-admin" in provision and ".env.maintenance" in provision
    assert ".env.maintenance" in worker and ".env.db-admin" not in worker

    application_example = (ROOT / ".env.production.example").read_text(
        encoding="utf-8"
    )
    assert "DB_ADMIN_PASSWORD=" not in application_example
    assert "MAINTENANCE_POSTGRES_PASSWORD=" not in application_example
    assert (ROOT / ".env.db-admin.example").is_file()
    assert (ROOT / ".env.maintenance.example").is_file()


def test_mobile_marked_experimental():
    assert (ROOT / "mobile" / "EXPERIMENTAL.md").is_file()
    text = (ROOT / "mobile" / "EXPERIMENTAL.md").read_text(encoding="utf-8")
    assert "experimental" in text.lower() or "實驗" in text


def test_credential_vault_default_outside_uploads():
    from app.services.credential_vault import get_credential_dir, ensure_credential_dir

    d = get_credential_dir()
    assert "uploads" not in d.parts or d.parts[-2:] != ("uploads", ".credentials")
    assert d.name == "credentials"
    assert "var" in d.parts
    ensured = ensure_credential_dir()
    assert ensured.is_dir()


def test_credential_vault_rejects_uploads_path(monkeypatch, tmp_path):
    from app.services import credential_vault as cv

    bad = tmp_path / "uploads" / ".credentials"
    # Simulate repo uploads by patching _REPO_ROOT
    monkeypatch.setattr(cv, "_REPO_ROOT", tmp_path)
    (tmp_path / "uploads").mkdir()
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_DIR", str(bad))
    import pytest

    with pytest.raises(ValueError, match="must not be under uploads"):
        cv.ensure_credential_dir()


def test_preflight_checks_compose_overlays():
    from app.services.deployment import run_preflight, DeploymentProfile

    r = run_preflight(DeploymentProfile.LITE)
    names = [c.get("check") or c.get("name") for c in r.checks]
    assert "compose_overlays" in names


def test_compose_config_profiles_lite_validates():
    """docker compose config must succeed for lite profile (no pull)."""
    import shutil
    import subprocess

    if not shutil.which("docker"):
        return
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.profiles.yml",
            "--profile",
            "lite",
            "config",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "web:" in result.stdout or "web" in result.stdout
