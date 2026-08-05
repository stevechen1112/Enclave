"""
形態 B 託管實例開通腳本（WS-AGENTIC-OPS 骨架）

人類僅在「確認交付」介入；本腳本負責：
  1. 產生客戶環境檔草稿
  2. 印出 Compose 拉起指令
  3. 可選：對已上線 URL 跑 managed_poc_smoke

真實雲端 VM／DNS／R2 建立仍需雲端憑證（本腳本不呼叫雲端 API）。

用法：
  python scripts/provision_managed_instance.py --customer acme --plan team --dry-run
  python scripts/provision_managed_instance.py --customer acme --plan team --write-env
  python scripts/provision_managed_instance.py --customer acme --enclave-url https://acme.example.com --smoke
"""
from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "ops"


def _gen_secret(n: int = 48) -> str:
    return secrets.token_urlsafe(n)


def build_env_content(*, customer: str, plan: str, domain: str) -> str:
    slug = customer.lower().replace(" ", "-")
    return f"""# Auto-generated managed instance env — {slug}
# Generated: {datetime.now(timezone.utc).isoformat()}
# Plan: {plan}
# WARNING: replace placeholder secrets before production.

APP_ENV=production
SECRET_KEY={_gen_secret()}
FIRST_SUPERUSER_EMAIL=admin@{slug}.example.com
FIRST_SUPERUSER_PASSWORD={_gen_secret(24)}

POSTGRES_SERVER=db
POSTGRES_USER=postgres
POSTGRES_PASSWORD={_gen_secret(24)}
POSTGRES_DB=enclave

REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD={_gen_secret(24)}
CELERY_BROKER_URL=redis://:CHANGE_ME@redis:6379/0
CELERY_RESULT_BACKEND=redis://:CHANGE_ME@redis:6379/0

BACKEND_CORS_ORIGINS=https://{domain}
FRONTEND_URL=https://{domain}
FRONTEND_BASE_URL=https://{domain}
BACKEND_BASE_URL=https://{domain}

STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://CHANGE_ME.r2.cloudflarestorage.com
S3_BUCKET=enclave-{slug}
S3_ACCESS_KEY=CHANGE_ME
S3_SECRET_KEY=CHANGE_ME
S3_REGION=auto

CLAMAV_ENABLED=true
CLAMAV_HOST=clamav
CLAMAV_PORT=3310
CLAMAV_FAIL_CLOSED=true

RATE_LIMIT_ENABLED=true
MFA_ENFORCE_OWNER=true
EMAIL_VERIFICATION_ENABLED=true

NEWEBPAY_MERCHANT_ID=
NEWEBPAY_HASH_KEY=
NEWEBPAY_HASH_IV=
NEWEBPAY_TEST_MODE=true

SENTRY_DSN=
LANGFUSE_ENABLED=false
"""


def compose_up_command() -> str:
    return (
        "docker compose "
        "--env-file .env.production "
        "--env-file compose/image-pins.env "
        "--env-file compose/pack-enabled.env "
        "-f docker-compose.prod.yml "
        "-f compose/sidecars.yml "
        "-f compose/clamav.yml "
        "--profile production up -d"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision managed private-cloud instance (skeleton)")
    parser.add_argument("--customer", required=True, help="Customer slug / short name")
    parser.add_argument("--plan", default="pilot", choices=["pilot", "team", "business", "enterprise"])
    parser.add_argument("--domain", default="", help="Customer FQDN (default: <customer>.example.com)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only")
    parser.add_argument("--write-env", action="store_true", help="Write artifacts/ops/<customer>.env.production")
    parser.add_argument("--enclave-url", default="", help="Live URL for smoke test")
    parser.add_argument("--smoke", action="store_true", help="Run managed_poc_smoke against --enclave-url")
    parser.add_argument("--confirm-delivery", action="store_true", help="Human gate: mark delivery confirmed")
    args = parser.parse_args()

    slug = args.customer.lower().replace(" ", "-")
    domain = args.domain or f"{slug}.example.com"
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    env_text = build_env_content(customer=slug, plan=args.plan, domain=domain)
    payload = {
        "action": "provision_managed_instance",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "customer": slug,
        "plan": args.plan,
        "domain": domain,
        "compose_up": compose_up_command(),
        "human_gate": "confirm-delivery",
        "destructive_ops_require_approval": True,
        "status": "PLANNED",
        "steps": [],
    }

    if args.dry_run or not (args.write_env or args.smoke or args.confirm_delivery):
        payload["status"] = "DRY_RUN"
        payload["steps"].append({"name": "preview", "passed": True})
        print(env_text)
        print("\n# Compose:\n" + compose_up_command())

    if args.write_env:
        out = ARTIFACT_DIR / f"{slug}.env.production"
        out.write_text(env_text, encoding="utf-8")
        payload["env_path"] = str(out)
        payload["steps"].append({"name": "write_env", "passed": True, "path": str(out)})
        payload["status"] = "ENV_WRITTEN"
        print(f"Wrote {out}")
        print("NEXT: copy to VM, fill S3/NewebPay/LLM secrets, then:")
        print(compose_up_command())

    if args.smoke:
        url = args.enclave_url or f"https://{domain}"
        env = {**dict(**{k: v for k, v in __import__("os").environ.items()}), "ENCLAVE_URL": url}
        proc = subprocess.run(
            [sys.executable, "scripts/managed_poc_smoke.py", "--skip-auth"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        ok = proc.returncode == 0
        payload["steps"].append({
            "name": "managed_poc_smoke",
            "passed": ok,
            "url": url,
            "detail": (proc.stdout or proc.stderr or "")[-400:],
        })
        payload["status"] = "SMOKE_PASS" if ok else "SMOKE_FAIL"

    if args.confirm_delivery:
        # 護欄：僅記錄人類批准，不執行破壞性操作
        payload["delivery_confirmed_at"] = datetime.now(timezone.utc).isoformat()
        payload["status"] = "DELIVERED"
        payload["steps"].append({"name": "confirm_delivery", "passed": True})

    log_path = ARTIFACT_DIR / f"provision_{slug}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Artifact: {log_path}")
    return 0 if payload["status"] not in ("SMOKE_FAIL",) else 1


if __name__ == "__main__":
    raise SystemExit(main())
