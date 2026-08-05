"""
託管私有雲 POC 煙霧測試（Phase 1 交付閘門）

驗證單一客戶實例在 Compose 拉起後的核心路徑：
  1. API / Gateway 健康
  2. Owner 登入（JWT）
  3. 用量儀表可讀
  4. 乾淨文件上傳（ClamAV 啟用時須通過掃毒）
  5. 可選：簡短聊天

環境變數：
  ENCLAVE_URL          預設 http://localhost:8000
  POC_OWNER_EMAIL      必填（除非 --skip-auth）
  POC_OWNER_PASSWORD   必填（除非 --skip-auth）

用法：
  python scripts/managed_poc_smoke.py
  python scripts/managed_poc_smoke.py --json
  python scripts/managed_poc_smoke.py --skip-upload --skip-chat

產物：artifacts/managed_poc_smoke_last_run.json
Exit 0：全部必檢項通過
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "managed_poc_smoke_last_run.json"
TEST_PDF = ROOT / "test-data" / "sample_manual.pdf"

ENCLAVE_URL = os.getenv("ENCLAVE_URL", "http://localhost:8000").rstrip("/")
OWNER_EMAIL = os.getenv("POC_OWNER_EMAIL", "")
OWNER_PASSWORD = os.getenv("POC_OWNER_PASSWORD", "")


class ManagedPocSmoke:
    def __init__(self, *, skip_auth: bool, skip_upload: bool, skip_chat: bool):
        self.skip_auth = skip_auth
        self.skip_upload = skip_upload
        self.skip_chat = skip_chat
        self.results: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}
        self.client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)

    def log(self, name: str, passed: bool, detail: str = ""):
        self.results.append({"name": name, "passed": passed, "detail": detail})
        icon = "PASS" if passed else "FAIL"
        print(f"  [{icon}] {name}" + (f" — {detail}" if detail else ""))

    async def check_api_health(self) -> None:
        try:
            r = await self.client.get(f"{ENCLAVE_URL}/health")
            self.log("API /health", r.status_code == 200, f"HTTP {r.status_code}")
        except Exception as exc:
            self.log("API /health", False, str(exc)[:120])

    async def check_gateway_health(self) -> None:
        try:
            r = await self.client.get(f"{ENCLAVE_URL}/api/v1/gateway/health")
            ok = r.status_code == 200
            detail = ""
            if ok:
                data = r.json()
                detail = f"gateway={data.get('gateway', '?')}"
            else:
                detail = f"HTTP {r.status_code}"
            self.log("Gateway health", ok, detail)
        except Exception as exc:
            self.log("Gateway health", False, str(exc)[:120])

    async def login_owner(self) -> None:
        if self.skip_auth:
            self.log("Owner login", True, "skipped")
            return
        if not OWNER_EMAIL or not OWNER_PASSWORD:
            self.log("Owner login", False, "POC_OWNER_EMAIL / POC_OWNER_PASSWORD 未設")
            return
        try:
            r = await self.client.post(
                f"{ENCLAVE_URL}/api/v1/auth/login/access-token",
                data={"username": OWNER_EMAIL, "password": OWNER_PASSWORD},
            )
            if r.status_code != 200:
                self.log("Owner login", False, f"HTTP {r.status_code}: {r.text[:100]}")
                return
            token = r.json().get("access_token")
            if not token:
                self.log("Owner login", False, "missing access_token")
                return
            self.headers = {"Authorization": f"Bearer {token}"}
            self.log("Owner login", True, OWNER_EMAIL)
        except Exception as exc:
            self.log("Owner login", False, str(exc)[:120])

    async def check_usage_summary(self) -> None:
        if self.skip_auth or not self.headers:
            self.log("Usage summary", True, "skipped (no auth)")
            return
        try:
            r = await self.client.get(
                f"{ENCLAVE_URL}/api/v1/company/usage/summary",
                headers=self.headers,
            )
            ok = r.status_code == 200
            detail = f"HTTP {r.status_code}"
            if ok:
                data = r.json()
                detail = f"keys={list(data.keys())[:5]}"
            self.log("Usage summary", ok, detail)
        except Exception as exc:
            self.log("Usage summary", False, str(exc)[:120])

    async def upload_clean_file(self) -> None:
        if self.skip_upload:
            self.log("Upload clean file", True, "skipped")
            return
        if not self.headers:
            self.log("Upload clean file", False, "no auth headers")
            return
        if not TEST_PDF.exists():
            self.log("Upload clean file", False, f"missing {TEST_PDF}")
            return
        try:
            with TEST_PDF.open("rb") as f:
                r = await self.client.post(
                    f"{ENCLAVE_URL}/api/v1/documents/upload",
                    headers=self.headers,
                    files={"file": (TEST_PDF.name, f, "application/pdf")},
                )
            ok = r.status_code in (200, 201)
            detail = f"HTTP {r.status_code}"
            if not ok:
                detail = f"HTTP {r.status_code}: {r.text[:120]}"
            self.log("Upload clean file", ok, detail)
        except Exception as exc:
            self.log("Upload clean file", False, str(exc)[:120])

    async def chat_smoke(self) -> None:
        if self.skip_chat:
            self.log("Chat smoke", True, "skipped")
            return
        if not self.headers:
            self.log("Chat smoke", False, "no auth headers")
            return
        try:
            r = await self.client.post(
                f"{ENCLAVE_URL}/api/v1/chat/",
                headers=self.headers,
                json={"message": "你好，這是託管 POC 煙霧測試。"},
            )
            ok = r.status_code == 200
            detail = f"HTTP {r.status_code}"
            if ok:
                body = r.json()
                detail = f"answer_len={len(str(body.get('answer', '')))}"
            else:
                detail = f"HTTP {r.status_code}: {r.text[:120]}"
            self.log("Chat smoke", ok, detail)
        except Exception as exc:
            self.log("Chat smoke", False, str(exc)[:120])

    def write_artifact(self) -> None:
        passed = sum(1 for r in self.results if r["passed"])
        failed = sum(1 for r in self.results if not r["passed"])
        payload = {
            "status": "PASS" if failed == 0 else "FAIL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "enclave_url": ENCLAVE_URL,
            "passed": passed,
            "failed": failed,
            "total": len(self.results),
            "results": self.results,
        }
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nArtifact: {ARTIFACT}")

    async def run(self) -> int:
        print("=" * 60)
        print("  Enclave Managed Private Cloud POC Smoke")
        print(f"  Target: {ENCLAVE_URL}")
        print("=" * 60)

        await self.check_api_health()
        await self.check_gateway_health()
        await self.login_owner()
        await self.check_usage_summary()
        await self.upload_clean_file()
        await self.chat_smoke()

        passed = sum(1 for r in self.results if r["passed"])
        failed = sum(1 for r in self.results if not r["passed"])
        print("\n" + "=" * 60)
        print(f"Results: {passed}/{len(self.results)} passed, {failed} failed")
        print("=" * 60)

        self.write_artifact()
        await self.client.aclose()
        return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Managed private cloud POC smoke test")
    parser.add_argument("--skip-auth", action="store_true", help="Only health checks")
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--skip-chat", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print artifact path only on success")
    args = parser.parse_args()

    smoke = ManagedPocSmoke(
        skip_auth=args.skip_auth,
        skip_upload=args.skip_upload,
        skip_chat=args.skip_chat,
    )
    code = asyncio.run(smoke.run())
    if args.json and code == 0:
        print(json.dumps({"artifact": str(ARTIFACT), "status": "PASS"}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
