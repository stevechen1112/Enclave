from pathlib import Path

from scripts.provision_p2_staging_env import PROVIDER_KEYS, build_files


def _parse(content: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in content.splitlines() if line)


def test_staging_credentials_are_split_and_force_rls_enabled():
    files = build_files(
        base_url="http://127.0.0.1:18080",
        image_prefix="enclave-staging",
        image_tag="source-sha",
    )
    app = _parse(files[".env.staging"])
    admin = _parse(files[".env.db-admin.staging"])
    maintenance = _parse(files[".env.maintenance.staging"])

    assert app["APP_ENV"] == "staging"
    assert app["RLS_ENFORCEMENT_ENABLED"] == "true"
    assert app["POSTGRES_USER"] == "enclave_app_staging"
    assert "DB_ADMIN_PASSWORD" not in app
    assert "MAINTENANCE_POSTGRES_PASSWORD" not in app
    assert admin["DB_ADMIN_USER"] == "postgres"
    assert maintenance["MAINTENANCE_POSTGRES_USER"] == "enclave_maintenance_staging"
    assert len({app["POSTGRES_PASSWORD"], admin["DB_ADMIN_PASSWORD"], maintenance["MAINTENANCE_POSTGRES_PASSWORD"]}) == 3


def test_staging_env_only_inherits_allowlisted_provider_values():
    inherited = {key: f"value-{key}" for key in PROVIDER_KEYS}
    inherited.update({"POSTGRES_PASSWORD": "never-copy", "S3_SECRET_KEY": "never-copy"})

    app = _parse(
        build_files(
            base_url="http://127.0.0.1:18080",
            image_prefix="enclave-staging",
            image_tag="source-sha",
            provider_values=inherited,
        )[".env.staging"]
    )

    assert all(app[key] == f"value-{key}" for key in PROVIDER_KEYS)
    assert app["POSTGRES_PASSWORD"] != "never-copy"
    assert "S3_SECRET_KEY" not in app
    assert app["VOICE_STT_ENABLED"] == "true"


def test_compose_honors_staging_app_env():
    compose = (Path(__file__).resolve().parents[1] / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "APP_ENV=production" not in compose
    assert compose.count("APP_ENV=${APP_ENV:-production}") == 5


def test_backend_runtime_contains_database_provisioning_and_gate_inputs():
    dockerignore = (Path(__file__).resolve().parents[1] / ".dockerignore").read_text(
        encoding="utf-8"
    )

    required = (
        "!config/tenant_security_catalog.json",
        "!config/tenant_session_exceptions.json",
        "!scripts/provision_tenant_database_roles.py",
        "!scripts/tenant_security_gate.py",
        "!scripts/tenant_session_context_gate.py",
        "!scripts/rls_shadow_report.py",
    )
    assert all(pattern in dockerignore for pattern in required)
