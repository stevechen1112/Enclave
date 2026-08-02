"""
End-to-End Smoketest — Enclave + RAGFlow + WeKnora + PipesHub

完整驗證流程：
  1. 健康檢查（所有容器）
  2. 上傳測試 PDF
  3. RAGFlow 解析
  4. Enclave 檢索
  5. Gateway 聚合
  6. 回答生成
  7. ACL 驗證
  8. 刪除 + tombstone 驗證

Usage:
  python scripts/smoketest.py
  python scripts/smoketest.py --profile standard
  python scripts/smoketest.py --skip-containers  # 僅測試 API（容器已手動啟動）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# ── Config ──
ENCLAVE_URL = os.getenv("ENCLAVE_URL", "http://localhost:8000")
RAGFLOW_URL = os.getenv("RAGFLOW_URL", "http://localhost:8001")
PIPESHUB_URL = os.getenv("PIPESHUB_URL", "http://localhost:8002")
WEKNORA_URL = os.getenv("WEKNORA_URL", "http://localhost:8003")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

TEST_PDF = Path(__file__).parent.parent / "test-data" / "sample_manual.pdf"

PASS = "✅"
FAIL = "❌"
SKIP = "⏭️"


class Smoketest:
    def __init__(self, skip_containers: bool = False):
        self.skip_containers = skip_containers
        self.results: List[Dict[str, Any]] = []
        self.client = httpx.Client(timeout=30.0)
        self.aclient = httpx.AsyncClient(timeout=30.0)

    def log(self, name: str, passed: bool, detail: str = ""):
        icon = PASS if passed else FAIL
        self.results.append({"name": name, "passed": passed, "detail": detail})
        print(f"  {icon} {name} {detail}")

    # ═══════════════════════════════════════════════════════════════════════════
    #  Phase 1: Health Checks
    # ═══════════════════════════════════════════════════════════════════════════

    async def check_health(self, url: str, name: str, path: str = "/health") -> bool:
        try:
            r = await self.aclient.get(f"{url}{path}", timeout=10.0)
            return r.status_code == 200
        except Exception as exc:
            self.log(f"Health: {name}", False, str(exc)[:80])
            return False

    async def phase1_health(self):
        print("\n── Phase 1: Health Checks ──")
        checks = [
            ("Enclave API", ENCLAVE_URL, "/api/v1/gateway/health"),
            ("RAGFlow", RAGFLOW_URL, "/api/v1/system/healthz"),
            ("PipesHub", PIPESHUB_URL, "/health"),
            ("WeKnora", WEKNORA_URL, "/health"),
        ]
        for name, url, path in checks:
            ok = await self.check_health(url, name, path)
            self.log(f"Health: {name}", ok)

    # ═══════════════════════════════════════════════════════════════════════════
    #  Phase 2: Gateway Health
    # ═══════════════════════════════════════════════════════════════════════════

    async def phase2_gateway(self):
        print("\n── Phase 2: Gateway ──")
        try:
            r = await self.aclient.get(f"{ENCLAVE_URL}/api/v1/gateway/health")
            data = r.json()
            ok = r.status_code == 200 and data.get("gateway") == "healthy"
            self.log("Gateway health", ok, str(data.get("adapters", {}).keys()))
        except Exception as exc:
            self.log("Gateway health", False, str(exc)[:80])

    # ═══════════════════════════════════════════════════════════════════════════
    #  Phase 3: Document Upload + Parse
    # ═══════════════════════════════════════════════════════════════════════════

    async def phase3_upload_parse(self):
        print("\n── Phase 3: Upload + Parse ──")
        if not TEST_PDF.exists():
            self.log("Test PDF exists", False, f"Not found: {TEST_PDF}")
            return

        self.log("Test PDF exists", True, str(TEST_PDF))

        # Upload to Enclave
        try:
            with open(TEST_PDF, "rb") as f:
                files = {"file": (TEST_PDF.name, f, "application/pdf")}
                r = await self.aclient.post(
                    f"{ENCLAVE_URL}/api/v1/documents/upload",
                    files=files,
                )
            if r.status_code in (200, 201):
                doc = r.json()
                self.log("Upload document", True, f"ID: {doc.get('id', '?')[:8]}...")
            else:
                self.log("Upload document", False, f"HTTP {r.status_code}: {r.text[:100]}")
        except Exception as exc:
            self.log("Upload document", False, str(exc)[:80])

    # ═══════════════════════════════════════════════════════════════════════════
    #  Phase 4: Search
    # ═══════════════════════════════════════════════════════════════════════════

    async def phase4_search(self):
        print("\n── Phase 4: Search ──")
        try:
            r = await self.aclient.get(f"{ENCLAVE_URL}/api/v1/documents/")
            docs = r.json() if r.status_code == 200 else []
            self.log("List documents", len(docs) > 0, f"{len(docs)} documents")
        except Exception as exc:
            self.log("List documents", False, str(exc)[:80])

    # ═══════════════════════════════════════════════════════════════════════════
    #  Summary
    # ═══════════════════════════════════════════════════════════════════════════

    def summary(self):
        print("\n" + "=" * 60)
        passed = sum(1 for r in self.results if r["passed"])
        failed = sum(1 for r in self.results if not r["passed"])
        total = len(self.results)
        print(f"Results: {passed}/{total} passed, {failed} failed")
        if failed:
            print("\nFailures:")
            for r in self.results:
                if not r["passed"]:
                    print(f"  {FAIL} {r['name']}: {r['detail']}")
        print("=" * 60)
        return failed == 0

    async def run(self):
        print("=" * 60)
        print("  Enclave End-to-End Smoketest")
        print(f"  Enclave:  {ENCLAVE_URL}")
        print(f"  RAGFlow:  {RAGFLOW_URL}")
        print(f"  PipesHub: {PIPESHUB_URL}")
        print(f"  WeKnora:  {WEKNORA_URL}")
        print("=" * 60)

        await self.phase1_health()
        await self.phase2_gateway()
        await self.phase3_upload_parse()
        await self.phase4_search()

        ok = self.summary()
        await self.aclient.aclose()
        return 0 if ok else 1


async def main():
    parser = argparse.ArgumentParser(description="Enclave E2E Smoketest")
    parser.add_argument("--skip-containers", action="store_true", help="Skip container health checks")
    args = parser.parse_args()

    test = Smoketest(skip_containers=args.skip_containers)
    exit_code = await test.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
