"""Register Ollama chat LLM in RAGFlow (required for RAPTOR / GraphRAG).

Idempotent: skips if llm_name already present in /v1/llm/list.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_NAME = os.getenv("RAGFLOW_CHAT_MODEL", "cwchang/llama-3-taiwan-8b-instruct:latest")
API_BASE = os.getenv("RAGFLOW_OLLAMA_BASE", "http://host.docker.internal:11434")


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
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main() -> int:
    _load_env()
    listed = api("GET", "/v1/llm/list")
    ollama = (listed.get("data") or {}).get("Ollama") or []
    names = {m.get("llm_name") for m in ollama}
    if CHAT_NAME in names:
        print(f"already present: {CHAT_NAME}")
    else:
        got = api("POST", "/v1/llm/add_llm", {
            "llm_factory": "Ollama",
            "llm_name": CHAT_NAME,
            "model_type": "chat",
            "api_base": API_BASE,
            # Must match embedding instance name used in tenant embd_id
            # (`bge-m3@ollama-local@Ollama`); otherwise RAPTOR raises
            # LookupError: Instance ollama-local not found.
            "api_key": "ollama-local",
            "max_tokens": 8192,
        })
        print("add_llm:", got)
    # Ensure ollama-local instance exists even if chat was added earlier with api_key=ollama
    try:
        got = api("POST", "/v1/llm/add_llm", {
            "llm_factory": "Ollama",
            "llm_name": CHAT_NAME,
            "model_type": "chat",
            "api_base": API_BASE,
            "api_key": "ollama-local",
            "max_tokens": 8192,
        })
        print("ensure ollama-local instance:", got)
    except Exception as exc:
        print("ensure instance skip:", exc)
    # Set tenant default chat model (required for RAPTOR/GraphRAG synthesis).
    # RAGFlow previously defaulted to qwen3:35b@ollama-local which may be missing.
    try:
        print("/api/v1/users/me/models", api("PATCH", "/api/v1/users/me/models", {
            "tenant_id": os.getenv("RAGFLOW_TENANT_ID", "8969c9e08d0011f18a66c5254d90938b"),
            "asr_id": "",
            "embd_id": "bge-m3@ollama-local@Ollama",
            "img2txt_id": "",
            # Triple form required: model@instance@factory. Two-part
            # `model@Ollama` resolves instance_name="default", which fails when
            # multiple Ollama instances exist (RAPTOR: Instance default not found).
            "llm_id": f"{CHAT_NAME}@ollama-local@Ollama",
        }))
    except Exception as exc:
        print("set tenant llm skip:", exc)
    listed = api("GET", "/v1/llm/list")
    print(json.dumps(listed.get("data"), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
