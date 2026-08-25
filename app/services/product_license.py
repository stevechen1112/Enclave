"""Phase 7 — Product module licensing."""
from __future__ import annotations

import os
from enum import Enum
from typing import Dict, Set


class ProductModule(str, Enum):
    BASE = "enclave_base"
    DOCUMENT_INTELLIGENCE = "document_intelligence_pack"
    ENTERPRISE_CONNECT = "enterprise_connect_pack"
    KNOWLEDGE_COMPILER = "knowledge_compiler_pack"
    AGENT_AUTOMATION = "agent_automation_pack"


MODULE_ENV_MAP = {
    ProductModule.DOCUMENT_INTELLIGENCE: "RAGFLOW_ENABLED",
    ProductModule.ENTERPRISE_CONNECT: "PIPESHUB_ENABLED",
    ProductModule.KNOWLEDGE_COMPILER: "WEKNORA_ENABLED",
    ProductModule.AGENT_AUTOMATION: "AGENT_AUTOMATION_ENABLED",
}


def enabled_modules() -> Set[str]:
    enabled = {ProductModule.BASE.value}
    for module, env_key in MODULE_ENV_MAP.items():
        if os.getenv(env_key, "").strip().lower() == "true":
            enabled.add(module.value)
    return enabled


def is_module_enabled(module: ProductModule) -> bool:
    if module == ProductModule.BASE:
        return True
    env_key = MODULE_ENV_MAP.get(module)
    return bool(env_key and os.getenv(env_key, "").strip().lower() == "true")


def module_status() -> Dict[str, bool]:
    return {m.value: is_module_enabled(m) for m in ProductModule}
