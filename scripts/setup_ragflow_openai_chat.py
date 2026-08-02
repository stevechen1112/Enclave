"""Register OpenAI chat LLM in RAGFlow and set as tenant default.

Replaces the local 8B Ollama chat model for RAPTOR / GraphRAG synthesis.
Idempotent: skips add if model already listed.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_NAME = os.getenv("RAGFLOW_OPENAI_CHAT_MODEL", "gpt-5.6-luna")
FACTORY = "OpenAI"


def _load_env():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def api(method: str, path: str, payload=None):
    base = os.environ["RAGFLOW_BASE_URL"].rstrip("/")
    key = os.environ["RAGFLOW_API_KEY"]
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base}{path}", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def main() -> int:
    _load_env()
    openai_key = os.environ["OPENAI_API_KEY"]

    listed = api("GET", "/v1/llm/list")
    openai_models = (listed.get("data") or {}).get(FACTORY) or []
    names = {m.get("llm_name") for m in openai_models}
    if CHAT_NAME in names:
        print(f"already present: {CHAT_NAME}")
    else:
        # set_api_key registers the factory key; add_llm registers the model.
        try:
            print("set_api_key:", api("POST", "/v1/llm/set_api_key", {
                "llm_factory": FACTORY,
                "api_key": openai_key,
            }))
        except Exception as exc:
            print("set_api_key skip:", exc)
        print("add_llm:", api("POST", "/v1/llm/add_llm", {
            "llm_factory": FACTORY,
            "llm_name": CHAT_NAME,
            "model_type": "chat",
            "api_key": openai_key,
            "max_tokens": 128000,
        }))

    print("/api/v1/users/me/models", api("PATCH", "/api/v1/users/me/models", {
        "tenant_id": os.getenv("RAGFLOW_TENANT_ID", "8969c9e08d0011f18a66c5254d90938b"),
        "asr_id": "",
        "embd_id": "bge-m3@ollama-local@Ollama",
        "img2txt_id": "",
        "llm_id": f"{CHAT_NAME}@{FACTORY}",
    }))

    listed = api("GET", "/v1/llm/list")
    data = listed.get("data") or {}
    print(json.dumps({FACTORY: [m.get("llm_name") for m in data.get(FACTORY) or []]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
