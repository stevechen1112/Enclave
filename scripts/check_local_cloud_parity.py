#!/usr/bin/env python3
"""Check local (.env/.env.production) and optional Linode env parity without leaking secrets.

Usage examples:
  python scripts/check_local_cloud_parity.py
  python scripts/check_local_cloud_parity.py --host <deployment-host> --user <operator> --key <key-path>
  python scripts/check_local_cloud_parity.py --remote-env /opt/enclave/.env.production
"""

from __future__ import annotations

import argparse
import re
import shlex
from collections.abc import Iterable
from pathlib import Path

PLACEHOLDER_PATTERNS = [
    r"^$",
    r"change_this",
    r"YOUR_REDIS_PASSWORD",
    r"your_service_token_here",
    r"yourdomain\.com",
    r"^sk-\.\.\.$",
    r"^voyage-\.\.\.$",
]

SENSITIVE_KEYS = {
    "SECRET_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "OPENAI_API_KEY",
    "VOYAGE_API_KEY",
    "LLAMAPARSE_API_KEY",
    "CORE_SERVICE_TOKEN",
    "FIRST_SUPERUSER_PASSWORD",
}


def parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def is_placeholder(value: str) -> bool:
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, value, flags=re.IGNORECASE):
            return True
    return False


def status(value: str) -> str:
    return "placeholder/empty" if is_placeholder(value) else "set"


def safe_view(key: str, value: str) -> str:
    if key in SENSITIVE_KEYS and value:
        if len(value) <= 8:
            return "***"
        return f"{value[:4]}...{value[-4:]}"
    return value


def print_coverage(title: str, base: dict[str, str], target: dict[str, str]) -> None:
    missing = sorted(k for k in base if k not in target)
    print(f"\n=== {title} ===")
    print(f"missing keys: {len(missing)}")
    if missing:
        print("sample missing:", ", ".join(missing[:12]))


def print_required(
    required: Iterable[str],
    local_prod: dict[str, str],
    local_dev: dict[str, str],
    remote: dict[str, str] | None,
) -> None:
    print("\n=== Required key sanity ===")
    for key in required:
        prod_v = local_prod.get(key, "")
        dev_v = local_dev.get(key, "")
        remote_v = remote.get(key, "") if remote else ""

        line = [
            f"{key}",
            f"prod={status(prod_v)}",
            f"dev={status(dev_v)}",
        ]
        if remote is not None:
            line.append(f"remote={status(remote_v)}")
        print(" | ".join(line))


def fetch_remote_env(
    host: str, user: str, key_file: str, remote_env: str
) -> dict[str, str]:
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko is required for remote checks. Install with: pip install paramiko") from exc

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(host, username=user, key_filename=key_file, timeout=20)
        cmd = f"cat -- {shlex.quote(remote_env)}"
        _, stdout, stderr = ssh.exec_command(cmd, timeout=20)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace").strip()
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            raise RuntimeError(f"failed to read remote env: {err}")

        env: dict[str, str] = {}
        for raw in out.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
        return env
    except (OSError, paramiko.SSHException) as exc:
        raise RuntimeError("remote environment check failed") from exc
    finally:
        ssh.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local/cloud env parity")
    parser.add_argument("--host", help="Remote host (optional)")
    parser.add_argument("--user", default="root", help="Remote SSH user")
    parser.add_argument("--key", dest="key_file", help="SSH private key path")
    parser.add_argument("--remote-env", default="/opt/enclave/.env.production", help="Remote env file path")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]

    env_example = parse_env_file(repo / ".env.example")
    env_dev = parse_env_file(repo / ".env")
    env_prod_example = parse_env_file(repo / ".env.production.example")
    env_prod = parse_env_file(repo / ".env.production")

    print_coverage("Local dev parity (.env.example vs .env)", env_example, env_dev)
    print_coverage("Local prod parity (.env.production.example vs .env.production)", env_prod_example, env_prod)

    remote_env = None
    if args.host and args.key_file:
        try:
            remote_env = fetch_remote_env(args.host, args.user, args.key_file, args.remote_env)
            print_coverage("Cloud parity (.env.production.example vs remote .env.production)", env_prod_example, remote_env)
        except RuntimeError as exc:
            print(f"\n[WARN] remote parity check skipped: {exc}")

    required = [
        "SECRET_KEY",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "OPENAI_API_KEY",
        "VOYAGE_API_KEY",
        "LLAMAPARSE_ENABLED",
        "LLAMAPARSE_API_KEY",
        "LLAMAPARSE_LANGUAGE",
        "OCR_LANGS",
        "FIRST_SUPERUSER_EMAIL",
        "FIRST_SUPERUSER_PASSWORD",
    ]
    print_required(required, env_prod, env_dev, remote_env)

    print("\n=== Key snapshots (masked) ===")
    snapshot_keys = [
        "OPENAI_MODEL",
        "VOYAGE_MODEL",
        "LLAMAPARSE_ENABLED",
        "LLAMAPARSE_LANGUAGE",
        "OCR_LANGS",
        "REDIS_PORT",
        "POSTGRES_SERVER",
    ]

    for key in snapshot_keys:
        dev_val = safe_view(key, env_dev.get(key, ""))
        prod_val = safe_view(key, env_prod.get(key, ""))
        msg = f"{key}: dev={dev_val or '(missing)'} | prod={prod_val or '(missing)'}"
        if remote_env is not None:
            remote_val = safe_view(key, remote_env.get(key, ""))
            msg += f" | remote={remote_val or '(missing)'}"
        print(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
