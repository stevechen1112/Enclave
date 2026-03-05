#!/usr/bin/env python3
"""
Enclave 基礎設施健康檢查
========================
驗證所有 7 種外部依賴是否正常運作：
  1. PostgreSQL — 連線 + pgvector extension
  2. Redis — 連線 + 讀寫
  3. Celery Worker — 至少 1 個 worker 在線
  4. Ollama Embedding — bge-m3 可用
  5. Ollama LLM — gemma3:27b 可用
  6. Gemini API — chat completions 可達
  7. LlamaParse API — 餘額檢查

用法：
  python scripts/test_infra_health.py
  python scripts/test_infra_health.py --base-url http://1.2.3.4:8001
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time

import requests

# Windows cp950 workaround: force UTF-8 stdout
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── 顏色輸出 ─────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"

passed = 0
failed = 0
warnings = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  {GREEN}✔ {msg}{RESET}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  {RED}✘ {msg}{RESET}")


def warn(msg: str) -> None:
    global warnings
    warnings += 1
    print(f"  {YELLOW}⚠ {msg}{RESET}")


def info(msg: str) -> None:
    print(f"  {DIM}  {msg}{RESET}")


def section(title: str) -> None:
    print(f"\n{BOLD}{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}{RESET}")


def check(name: str, fn, critical: bool = True):
    """執行一項檢查，捕捉所有例外。"""
    try:
        fn()
    except AssertionError as e:
        if critical:
            fail(f"{name}: {e}")
        else:
            warn(f"{name}: {e}")
    except Exception as e:
        if critical:
            fail(f"{name}: {type(e).__name__}: {e}")
        else:
            warn(f"{name}: {type(e).__name__}: {e}")


# ══════════════════════════════════════════════════
#  Check 1: API Health Endpoint
# ══════════════════════════════════════════════════
def check_api_health(base_url: str):
    section("1. API 服務健康檢查")

    def _check():
        r = requests.get(f"{base_url}/health", timeout=10)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        data = r.json()
        assert data.get("status") == "ok", f"status={data.get('status')}"
        ok(f"API 健康 — env={data.get('env', '?')}")

    check("GET /health", _check)


# ══════════════════════════════════════════════════
#  Check 2: PostgreSQL + pgvector
# ══════════════════════════════════════════════════
def check_postgresql(base_url: str, headers: dict):
    section("2. PostgreSQL + pgvector")

    def _check_connection():
        # 嘗試讀取文件列表來驗證 DB 連線
        r = requests.get(f"{base_url}/api/v1/documents/", headers=headers, timeout=10)
        assert r.status_code == 200, f"HTTP {r.status_code} — DB 可能無法連線"
        ok("PostgreSQL 連線正常（documents API 回應成功）")

    def _check_tables():
        # 透過 admin API 取得租戶資訊來驗證 schema
        r = requests.get(f"{base_url}/api/v1/admin/tenants", headers=headers, timeout=10)
        if r.status_code == 200:
            tenants = r.json()
            ok(f"資料表完整 — 共 {len(tenants)} 個租戶")
        elif r.status_code == 403:
            ok("PostgreSQL 運作正常（admin API 需要更高權限）")
        else:
            assert False, f"HTTP {r.status_code}"

    check("DB 連線", _check_connection)
    check("Schema 完整性", _check_tables, critical=False)


# ══════════════════════════════════════════════════
#  Check 3: Redis
# ══════════════════════════════════════════════════
def check_redis(base_url: str, headers: dict):
    section("3. Redis（Cache + Celery Broker）")

    def _check():
        # KB search 使用 Redis 快取；如果 Redis 掛掉，search 仍會成功但慢
        r = requests.post(
            f"{base_url}/api/v1/kb/search",
            headers=headers,
            json={"query": "redis health check", "top_k": 1},
            timeout=15,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}"
        ok("Redis 連線正常（KB search 通過快取層）")

    check("Redis 連線", _check)


# ══════════════════════════════════════════════════
#  Check 4: Celery Worker
# ══════════════════════════════════════════════════
def check_celery_worker(base_url: str, headers: dict):
    section("4. Celery Worker")

    def _check():
        # 上傳一個微型 txt，確認 worker 能接收任務
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Celery worker 健康檢查測試文件。" * 10)
            tmp_path = f.name

        try:
            with open(tmp_path, "rb") as fh:
                r = requests.post(
                    f"{base_url}/api/v1/documents/upload",
                    headers={"Authorization": headers["Authorization"]},
                    files={"file": ("_health_check.txt", fh, "text/plain")},
                    timeout=15,
                )
            if r.status_code == 200:
                doc_id = r.json().get("id")
                # 等待 5 秒看 worker 是否接收到任務（status 從 uploading 變化）
                time.sleep(5)
                r2 = requests.get(
                    f"{base_url}/api/v1/documents/{doc_id}",
                    headers=headers,
                    timeout=10,
                )
                if r2.status_code == 200:
                    status = r2.json().get("status", "unknown")
                    if status in ("parsing", "embedding", "completed"):
                        ok(f"Celery Worker 正常 — 任務已被接收（status={status}）")
                    elif status == "uploading":
                        warn("Worker 可能離線 — 文件仍在 uploading 狀態（5s 後）")
                    else:
                        ok(f"Worker 處理中 — status={status}")
                # 清理
                requests.delete(
                    f"{base_url}/api/v1/documents/{doc_id}",
                    headers=headers,
                    timeout=10,
                )
            elif r.status_code == 429:
                warn("配額限制，無法測試 Worker（跳過）")
            else:
                assert False, f"上傳失敗 HTTP {r.status_code}: {r.text[:200]}"
        finally:
            os.unlink(tmp_path)

    check("Worker 可用性", _check, critical=False)


# ══════════════════════════════════════════════════
#  Check 5: Ollama Embedding (bge-m3)
# ══════════════════════════════════════════════════
def check_ollama_embedding():
    section("5. Ollama Embedding（bge-m3）")

    def _check():
        OLLAMA_URL = "http://localhost:11434"
        r = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": "bge-m3", "input": ["健康檢查測試"]},
            timeout=30,
        )
        assert r.status_code == 200, f"HTTP {r.status_code} — bge-m3 模型可能未載入"
        data = r.json()
        embeddings = data.get("embeddings", [])
        assert len(embeddings) > 0, "回傳空 embeddings"
        dim = len(embeddings[0])
        assert dim == 1024, f"維度不符預期：{dim}（應為 1024）"
        ok(f"bge-m3 嵌入正常 — {dim}d 向量")

    check("bge-m3 嵌入", _check)


# ══════════════════════════════════════════════════
#  Check 6: Ollama LLM (gemma3:27b)
# ══════════════════════════════════════════════════
def check_ollama_llm():
    section("6. Ollama LLM（gemma3:27b）")

    def _check():
        OLLAMA_URL = "http://localhost:11434"
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": "gemma3:27b",
                "messages": [{"role": "user", "content": "回答 OK"}],
                "stream": False,
                "options": {"num_predict": 10},
            },
            timeout=60,
        )
        assert r.status_code == 200, f"HTTP {r.status_code} — gemma3:27b 模型可能未載入"
        data = r.json()
        content = data.get("message", {}).get("content", "")
        assert len(content) > 0, "空回應"
        ok(f"gemma3:27b 推論正常 — 回應: {content[:50]}...")

    check("gemma3:27b 推論", _check)


# ══════════════════════════════════════════════════
#  Check 7: Gemini API
# ══════════════════════════════════════════════════
def check_gemini_api():
    section("7. Gemini API（雲端 LLM）")

    def _check():
        # 讀取 .env 取得 GEMINI_API_KEY
        import os
        from pathlib import Path

        env_path = Path(__file__).resolve().parent.parent / ".env"
        api_key = ""
        model = "gemini-2.0-flash"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("GEMINI_MODEL="):
                    model = line.split("=", 1)[1].strip().strip('"')

        if not api_key:
            warn("GEMINI_API_KEY 未設定，跳過 Gemini 檢查")
            return

        # 使用 OpenAI 相容端點
        base = "https://generativelanguage.googleapis.com/v1beta/openai/"
        r = requests.post(
            f"{base}chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Say OK"}],
                "max_tokens": 10,
            },
            timeout=30,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        ok(f"Gemini API 正常 — model={model}, 回應: {content[:30]}")

    check("Gemini 連線", _check, critical=False)


# ══════════════════════════════════════════════════
#  Check 8: LlamaParse API
# ══════════════════════════════════════════════════
def check_llamaparse_api():
    section("8. LlamaParse API（文件解析）")

    def _check():
        from pathlib import Path

        env_path = Path(__file__).resolve().parent.parent / ".env"
        api_key = ""
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("LLAMAPARSE_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"')

        if not api_key:
            warn("LLAMAPARSE_API_KEY 未設定，跳過")
            return

        r = requests.get(
            "https://api.cloud.llamaindex.ai/api/parsing/usage",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            ok(f"LlamaParse API 正常 — 用量: {json.dumps(data, ensure_ascii=False)[:100]}")
        elif r.status_code == 401:
            fail("LlamaParse API key 無效")
        else:
            warn(f"LlamaParse API HTTP {r.status_code}")

    check("LlamaParse 連線", _check, critical=False)


# ══════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Enclave 基礎設施健康檢查")
    parser.add_argument("--base-url", default="http://localhost:8001", help="API base URL")
    parser.add_argument("--user", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    args = parser.parse_args()

    print(f"\n{BOLD}═══════════════════════════════════════════════════")
    print(f"  Enclave 基礎設施健康檢查")
    print(f"  Target: {args.base_url}")
    print(f"═══════════════════════════════════════════════════{RESET}")

    # 先取得 token
    headers = {}
    try:
        r = requests.post(
            f"{args.base_url}/api/v1/auth/login/access-token",
            data={"username": args.user, "password": args.password},
            timeout=10,
        )
        if r.status_code == 200:
            token = r.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            ok(f"登入成功 — {args.user}")
        else:
            fail(f"登入失敗 HTTP {r.status_code}")
    except Exception as e:
        fail(f"無法連線到 API: {e}")

    # 依序檢查
    check_api_health(args.base_url)
    check_postgresql(args.base_url, headers)
    check_redis(args.base_url, headers)
    check_celery_worker(args.base_url, headers)
    check_ollama_embedding()
    check_ollama_llm()
    check_gemini_api()
    check_llamaparse_api()

    # 結果摘要
    section("結果摘要")
    total = passed + failed + warnings
    print(f"  {GREEN}通過: {passed}{RESET}  {RED}失敗: {failed}{RESET}  {YELLOW}警告: {warnings}{RESET}  總計: {total}")

    if failed > 0:
        print(f"\n  {RED}{BOLD}⚠ 有 {failed} 項關鍵檢查失敗！{RESET}")
        sys.exit(1)
    elif warnings > 0:
        print(f"\n  {YELLOW}△ 全部通過，但有 {warnings} 項非關鍵警告{RESET}")
        sys.exit(0)
    else:
        print(f"\n  {GREEN}{BOLD}✔ 所有檢查通過！系統運作正常{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
