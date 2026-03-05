from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import SessionLocal
from app.models.feature_flag import FeatureFlag


DEPLOYMENT_MODE_FLAG_KEY = "deployment_mode"
DEPLOYMENT_MODE_GPU = "gpu"
DEPLOYMENT_MODE_NOGPU = "nogpu"
_VALID_MODES = {DEPLOYMENT_MODE_GPU, DEPLOYMENT_MODE_NOGPU}


def _model_for_provider(provider: str, role: str) -> str:
    provider = (provider or "").lower()
    if role == "main":
        if provider == "gemini":
            return getattr(settings, "GEMINI_MODEL", "gemini-3-flash-preview")
        if provider == "openai":
            return getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")
        return getattr(settings, "OLLAMA_MODEL", "llama3.2")

    if role == "internal":
        if provider == "gemini":
            return getattr(settings, "INTERNAL_GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
        if provider == "openai":
            return getattr(settings, "INTERNAL_OPENAI_MODEL", "gpt-4o-mini")
        return getattr(settings, "INTERNAL_OLLAMA_MODEL", "gemma3:27b")

    if role == "scan":
        if provider == "gemini":
            return getattr(settings, "SCAN_GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
        if provider == "openai":
            return getattr(settings, "SCAN_OPENAI_MODEL", "gpt-4o-mini")
        return getattr(settings, "OLLAMA_SCAN_MODEL", "gemma3:27b")

    if provider == "voyage":
        return getattr(settings, "VOYAGE_MODEL", "voyage-4-lite")
    return getattr(settings, "OLLAMA_EMBED_MODEL", "bge-m3")


def get_deployment_mode(db: Session) -> str:
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == DEPLOYMENT_MODE_FLAG_KEY).first()
    metadata = (flag.metadata_ or {}) if flag else {}
    mode = str(metadata.get("mode", DEPLOYMENT_MODE_NOGPU)).lower()
    if mode not in _VALID_MODES:
        return DEPLOYMENT_MODE_NOGPU
    return mode


def set_deployment_mode(db: Session, mode: str) -> str:
    normalized = (mode or "").strip().lower()
    if normalized not in _VALID_MODES:
        raise ValueError("mode 必須為 gpu 或 nogpu")

    flag = db.query(FeatureFlag).filter(FeatureFlag.key == DEPLOYMENT_MODE_FLAG_KEY).first()
    if not flag:
        flag = FeatureFlag(
            key=DEPLOYMENT_MODE_FLAG_KEY,
            description="Runtime deployment mode preset (gpu / nogpu)",
            enabled=True,
            rollout_percentage=100,
            metadata_={"mode": normalized},
        )
        db.add(flag)
    else:
        metadata = dict(flag.metadata_ or {})
        metadata["mode"] = normalized
        flag.metadata_ = metadata
        flag.enabled = True
        flag.rollout_percentage = 100
    db.commit()
    return normalized


def resolve_runtime_profiles(db: Session) -> Dict[str, Any]:
    mode = get_deployment_mode(db)

    if mode == DEPLOYMENT_MODE_GPU:
        return {
            "mode": mode,
            "main": {
                "provider": "ollama",
                "model": "qwen3.5:27b",
                "base_url": getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434"),
            },
            "internal": {
                "provider": "ollama",
                "model": "qwen3:14b",
                "base_url": getattr(settings, "OLLAMA_SCAN_URL", "http://host.docker.internal:11434"),
            },
            "scan": {
                "provider": "ollama",
                "model": "qwen3:14b",
                "base_url": getattr(settings, "OLLAMA_SCAN_URL", "http://host.docker.internal:11434"),
            },
            "embedding": {
                "provider": "ollama",
                "model": "bge-m3:latest",
            },
        }

    main_provider = getattr(settings, "LLM_PROVIDER", "openai").lower()
    internal_provider = getattr(settings, "INTERNAL_LLM_PROVIDER", "ollama").lower()
    scan_provider = getattr(settings, "SCAN_LLM_PROVIDER", "ollama").lower()
    embedding_provider = getattr(settings, "EMBEDDING_PROVIDER", "ollama").lower()

    return {
        "mode": mode,
        "main": {
            "provider": main_provider,
            "model": _model_for_provider(main_provider, "main"),
            "base_url": getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434"),
        },
        "internal": {
            "provider": internal_provider,
            "model": _model_for_provider(internal_provider, "internal"),
            "base_url": getattr(settings, "OLLAMA_SCAN_URL", "http://host.docker.internal:11434"),
        },
        "scan": {
            "provider": scan_provider,
            "model": _model_for_provider(scan_provider, "scan"),
            "base_url": getattr(settings, "OLLAMA_SCAN_URL", "http://host.docker.internal:11434"),
        },
        "embedding": {
            "provider": embedding_provider,
            "model": _model_for_provider(embedding_provider, "embedding"),
        },
    }


def resolve_runtime_profiles_no_db() -> Dict[str, Any]:
    db = SessionLocal()
    try:
        return resolve_runtime_profiles(db)
    finally:
        db.close()
