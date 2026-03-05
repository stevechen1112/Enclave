#!/usr/bin/env python3
"""
Enclave 環境檢查工具 (P9-4)

執行方式：
  python scripts/check_env.py          # 檢查 .env 設定
  python scripts/check_env.py --full   # 包含連線測試

退出碼：
  0 = 全部通過
  1 = 有錯誤（阻擋啟動）
  2 = 有警告（可繼續但建議處理）
"""
import os
import sys
import argparse
from pathlib import Path

# 嘗試載入 .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # 沒有 python-dotenv 也可以跑，從系統環境變數讀

ERRORS = []
WARNINGS = []
OK = []


def check(label: str, condition: bool, message: str, is_error: bool = True):
    if condition:
        OK.append(f"  ✅  {label}")
    else:
        if is_error:
            ERRORS.append(f"  ❌  {label}: {message}")
        else:
            WARNINGS.append(f"  ⚠️   {label}: {message}")


# ── 必填設定 ──────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "")
check(
    "SECRET_KEY",
    len(SECRET_KEY) >= 32 and SECRET_KEY != "change_this_to_a_secure_random_string_at_least_32_chars",
    "未設定或仍使用範本值，請執行 python scripts/dev/gen_hash.py 產生安全金鑰"
)

POSTGRES_SERVER = os.getenv("POSTGRES_SERVER", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "enclave")
check("POSTGRES_SERVER", bool(POSTGRES_SERVER), "未設定 POSTGRES_SERVER")
check("POSTGRES_DB", POSTGRES_DB == "enclave", f"資料庫名稱應為 enclave，目前為 {POSTGRES_DB}", is_error=False)

# ── LLM 設定 ──────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
check("LLM_PROVIDER", LLM_PROVIDER in ("openai", "gemini", "ollama"), f"LLM_PROVIDER 必須為 openai、gemini 或 ollama，目前為 {LLM_PROVIDER}")

if LLM_PROVIDER == "gemini":
    GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
    check(
        "GEMINI_API_KEY",
        bool(GEMINI_KEY) and GEMINI_KEY != "AIza...",
        "使用 gemini 模式但 GEMINI_API_KEY 未設定"
    )
    VOYAGE_KEY = os.getenv("VOYAGE_API_KEY", "")
    check(
        "VOYAGE_API_KEY",
        bool(VOYAGE_KEY) and VOYAGE_KEY != "voyage-...",
        "VOYAGE_API_KEY 未設定（向量搜尋品質會下降）",
        is_error=False
    )
elif LLM_PROVIDER == "openai":
    OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
    check(
        "OPENAI_API_KEY",
        bool(OPENAI_KEY) and OPENAI_KEY != "sk-...",
        "使用 openai 模式但 OPENAI_API_KEY 未設定"
    )
    VOYAGE_KEY = os.getenv("VOYAGE_API_KEY", "")
    check(
        "VOYAGE_API_KEY",
        bool(VOYAGE_KEY) and VOYAGE_KEY != "voyage-...",
        "VOYAGE_API_KEY 未設定（向量搜尋品質會下降）",
        is_error=False
    )
elif LLM_PROVIDER == "ollama":
    OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "")
    check("OLLAMA_BASE_URL", bool(OLLAMA_URL), "未設定 OLLAMA_BASE_URL")
    check("OLLAMA_MODEL", bool(OLLAMA_MODEL), "未設定 OLLAMA_MODEL（建議使用 llama3.2 或 qwen2.5）")

# ── Admin 帳號設定 ──────────────────────────────────
ADMIN_EMAIL = os.getenv("FIRST_SUPERUSER_EMAIL", "")
ADMIN_PWD = os.getenv("FIRST_SUPERUSER_PASSWORD", "")
check("FIRST_SUPERUSER_EMAIL", bool(ADMIN_EMAIL) and "@" in ADMIN_EMAIL, "未設定管理員 Email")
check(
    "FIRST_SUPERUSER_PASSWORD",
    len(ADMIN_PWD) >= 8 and ADMIN_PWD not in ("請立即修改此密碼", "admin123"),
    "管理員密碼未設定或過於簡單（至少 8 字元）"
)

# ── Agent 設定（選填）──────────────────────────────
AGENT_ENABLED = os.getenv("AGENT_WATCH_ENABLED", "false").lower() == "true"
if AGENT_ENABLED:
    WATCH_FOLDERS = os.getenv("AGENT_WATCH_FOLDERS", "")
    check("AGENT_WATCH_FOLDERS", bool(WATCH_FOLDERS), "已啟用 Agent 但未設定 AGENT_WATCH_FOLDERS")
    if WATCH_FOLDERS:
        for folder in WATCH_FOLDERS.split(","):
            folder = folder.strip()
            check(
                f"資料夾存在: {folder}",
                os.path.isdir(folder),
                f"資料夾不存在或無法存取，請確認容器掛載路徑",
                is_error=False
            )


def test_connections():
    """選用：實際連線測試"""
    print("\n── 連線測試 ──────────────────────────")

    # PostgreSQL
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_SERVER", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            dbname=os.getenv("POSTGRES_DB", "enclave"),
            connect_timeout=5,
        )
        conn.close()
        print("  ✅  PostgreSQL 連線成功")
    except Exception as e:
        print(f"  ❌  PostgreSQL 連線失敗: {e}")

    # Redis
    try:
        import redis
        r = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            socket_connect_timeout=3,
        )
        r.ping()
        print("  ✅  Redis 連線成功")
    except Exception as e:
        print(f"  ❌  Redis 連線失敗: {e}")

    # Ollama（若使用）
    if LLM_PROVIDER == "ollama":
        try:
            import urllib.request
            ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=5)
            print(f"  ✅  Ollama 連線成功（{ollama_url}）")
        except Exception as e:
            print(f"  ❌  Ollama 連線失敗: {e}")


# ── 輸出結果 ──────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Enclave 環境檢查工具")
    parser.add_argument("--full", action="store_true", help="包含實際連線測試")
    args = parser.parse_args()

    print("=" * 48)
    print("  Enclave 環境設定檢查")
    print("=" * 48)

    if OK:
        print("\n── 通過 ─────────────────────────────────")
        for msg in OK:
            print(msg)

    if WARNINGS:
        print("\n── 警告（不影響啟動）────────────────────")
        for msg in WARNINGS:
            print(msg)

    if ERRORS:
        print("\n── 錯誤（必須修正）─────────────────────")
        for msg in ERRORS:
            print(msg)

    if args.full:
        test_connections()

    print("\n" + "=" * 48)
    if ERRORS:
        print(f"  ❌  檢查未通過：{len(ERRORS)} 個錯誤，{len(WARNINGS)} 個警告")
        print("  請修正 .env 中的錯誤後再啟動服務")
        sys.exit(1)
    elif WARNINGS:
        print(f"  ⚠️   檢查通過（含警告）：{len(WARNINGS)} 個警告")
        sys.exit(2)
    else:
        print(f"  ✅  所有檢查通過（{len(OK)} 項）")
        sys.exit(0)


if __name__ == "__main__":
    main()
