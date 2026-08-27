"""Create isolated, production-like P2 staging credentials.

The three output files deliberately keep the application, schema-owner, and
audited maintenance credentials separate. Existing files are never replaced
unless the operator explicitly passes ``--force``.
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

PROVIDER_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "VOYAGE_API_KEY",
    "VOYAGE_MODEL",
)


def _read_env(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _secret() -> str:
    return secrets.token_urlsafe(36)


def build_files(
    *,
    base_url: str,
    image_prefix: str,
    image_tag: str,
    provider_values: dict[str, str] | None = None,
) -> dict[str, str]:
    provider_values = provider_values or {}
    app_password = _secret()
    redis_password = _secret()
    openai_enabled = bool(provider_values.get("OPENAI_API_KEY"))
    provider_lines = [
        f"{key}={provider_values[key]}"
        for key in PROVIDER_KEYS
        if provider_values.get(key)
    ]
    app = [
        "APP_ENV=staging",
        f"SECRET_KEY={_secret()}",
        "FIRST_SUPERUSER_EMAIL=staging-admin@enclave.invalid",
        f"FIRST_SUPERUSER_PASSWORD={_secret()}",
        "POSTGRES_SERVER=db",
        "POSTGRES_USER=enclave_app_staging",
        f"POSTGRES_PASSWORD={app_password}",
        "POSTGRES_DB=enclave_staging",
        "RLS_ENFORCEMENT_ENABLED=true",
        "REDIS_HOST=redis",
        "REDIS_PORT=6379",
        f"REDIS_PASSWORD={redis_password}",
        f"CELERY_BROKER_URL=redis://:{redis_password}@redis:6379/0",
        f"CELERY_RESULT_BACKEND=redis://:{redis_password}@redis:6379/0",
        f"BACKEND_CORS_ORIGINS={base_url}",
        f"FRONTEND_URL={base_url}",
        "ADMIN_IP_WHITELIST_ENABLED=true",
        "ADMIN_IP_WHITELIST=127.0.0.1,::1,172.16.0.0/12",
        "ADMIN_TRUSTED_PROXY_IPS=127.0.0.1,::1,172.16.0.0/12",
        "RATE_LIMIT_ENABLED=true",
        "CLAMAV_ENABLED=false",
        "CLAMAV_FAIL_CLOSED=false",
        "LLAMAPARSE_ENABLED=false",
        "RAGFLOW_ENABLED=false",
        "PIPESHUB_ENABLED=false",
        "WEKNORA_ENABLED=false",
        "EMBEDDING_PROVIDER=ollama",
        "OLLAMA_EMBED_URL=http://ollama-embed:11434",
        "OLLAMA_EMBED_MODEL=bge-m3",
        "EMBEDDING_DIMENSION=1024",
        f"VOICE_STT_ENABLED={'true' if openai_enabled else 'false'}",
        "VOICE_STT_PROVIDER=openai",
        "VIDEO_INGESTION_ENABLED=true",
        "GRAFANA_USER=admin",
        f"GRAFANA_PASSWORD={_secret()}",
        f"GRAFANA_ROOT_URL={base_url}",
        "GATEWAY_HTTP_PORT=18080",
        "GATEWAY_HTTPS_PORT=18443",
        "GATEWAY_CONF=gateway.conf",
        "APP_ENV_FILE=.env.staging",
        "DB_ADMIN_ENV_FILE=.env.db-admin.staging",
        "MAINTENANCE_ENV_FILE=.env.maintenance.staging",
        f"IMAGE_PREFIX={image_prefix}",
        f"IMAGE_TAG={image_tag}",
        *provider_lines,
    ]
    admin = [
        "DB_ADMIN_HOST=db",
        "DB_ADMIN_PORT=5432",
        "DB_ADMIN_DATABASE=enclave_staging",
        "DB_ADMIN_USER=postgres",
        f"DB_ADMIN_PASSWORD={_secret()}",
    ]
    maintenance = [
        "MAINTENANCE_POSTGRES_USER=enclave_maintenance_staging",
        f"MAINTENANCE_POSTGRES_PASSWORD={_secret()}",
    ]
    return {
        ".env.staging": "\n".join(app) + "\n",
        ".env.db-admin.staging": "\n".join(admin) + "\n",
        ".env.maintenance.staging": "\n".join(maintenance) + "\n",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--image-prefix", default="enclave-staging")
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--inherit-provider-env", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = build_files(
        base_url=args.base_url.rstrip("/"),
        image_prefix=args.image_prefix,
        image_tag=args.image_tag,
        provider_values=_read_env(args.inherit_provider_env),
    )
    targets = [args.output_dir / name for name in files]
    existing = [str(path) for path in targets if path.exists()]
    if existing and not args.force:
        parser.error("refusing to replace existing staging secrets: " + ", ".join(existing))
    for name, content in files.items():
        target = args.output_dir / name
        target.write_text(content, encoding="utf-8")
        target.chmod(0o600)
    print(f"Created {len(files)} isolated staging credential files in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
