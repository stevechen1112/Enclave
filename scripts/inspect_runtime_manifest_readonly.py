#!/usr/bin/env python3
"""Print non-secret runtime identifiers for deployment evidence."""
from __future__ import annotations

import hashlib
import inspect
import json

from app.config import settings
from app.services.chat_orchestrator import ChatOrchestrator


NAMES = (
    "OPENAI_MODEL", "EMBEDDING_PROVIDER", "VOYAGE_MODEL", "OLLAMA_EMBED_MODEL",
    "EMBEDDING_DIMENSION", "RETRIEVAL_MODE", "RETRIEVAL_RERANK",
    "SOURCE_VERIFY_MODE", "PAGEINDEX_ENABLED", "HR_COMPATIBILITY_PACK_ENABLED",
    "RLS_ENFORCEMENT_ENABLED", "DEMO_LOGIN_ENABLED",
)


def main() -> int:
    values = {name: getattr(settings, name, None) for name in NAMES}
    try:
        prompt = str(ChatOrchestrator.SYSTEM_PROMPT)
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    except (AttributeError, TypeError):
        prompt_hash = hashlib.sha256(inspect.getsource(ChatOrchestrator).encode()).hexdigest()
    print(json.dumps({"runtime": values, "prompt_hash": prompt_hash}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
