"""OpenAI Chat Completions parameter compatibility helpers.

Newer models (e.g. gpt-5.6-luna) reject legacy params such as max_tokens /
non-default temperature. Build kwargs once and reuse across orchestrator /
llm_client / generate paths.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _is_gpt5_family(model: str) -> bool:
    m = (model or "").lower()
    return m.startswith("gpt-5") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4")


def chat_completion_kwargs(
    model: str,
    *,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    stream: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return create() kwargs safe for the given model id."""
    kwargs: Dict[str, Any] = {"model": model}
    if stream:
        kwargs["stream"] = True

    if max_tokens is not None:
        if _is_gpt5_family(model):
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

    if temperature is not None:
        if _is_gpt5_family(model):
            # gpt-5.x currently only accepts default temperature (1); omit otherwise.
            if float(temperature) == 1.0:
                kwargs["temperature"] = 1.0
        else:
            kwargs["temperature"] = temperature

    if extra:
        kwargs.update(extra)
    return kwargs
