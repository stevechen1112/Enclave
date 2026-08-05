"""UX experience bootstrap — capabilities, packs, deployment boundary (UIUX 2.0)."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.models.user import User
from app.services.product_license import ProductModule, module_status

router = APIRouter()

# Formal roles only — manager is not a UserRole
_ROLE_CAPS: Dict[str, List[str]] = {
    "owner": [
        "ask", "browse_knowledge", "upload_documents", "manage_sources",
        "review_queue", "governance", "system_ops", "create_content",
        "view_usage", "admin_home",
    ],
    "admin": [
        "ask", "browse_knowledge", "upload_documents", "manage_sources",
        "review_queue", "governance", "system_ops", "create_content",
        "view_usage", "admin_home",
    ],
    "hr": [
        "ask", "browse_knowledge", "upload_documents", "create_content", "view_usage",
    ],
    "employee": [
        "ask", "browse_knowledge", "create_content", "view_usage",
    ],
    "viewer": [
        "ask", "browse_knowledge", "view_usage",
    ],
}


def _capabilities_for(user: User) -> List[str]:
    role = (user.role or "employee").lower()
    caps = list(_ROLE_CAPS.get(role, _ROLE_CAPS["employee"]))
    if user.is_superuser:
        for c in ("system_ops", "governance", "admin_home", "review_queue", "manage_sources"):
            if c not in caps:
                caps.append(c)
    return caps


def _inference_boundary(db: Session) -> Dict[str, Any]:
    """Honest data-boundary signal for UI (local vs external model)."""
    try:
        from app.services.deployment_mode import resolve_runtime_profiles

        profiles = resolve_runtime_profiles(db)
        main_provider = str((profiles.get("main") or {}).get("provider") or "ollama").lower()
    except Exception:
        main_provider = str(os.getenv("LLM_PROVIDER") or "ollama").lower()

    external = main_provider in ("gemini", "openai", "anthropic", "azure")
    return {
        "mode": "external_model" if external else "local_model",
        "main_provider": main_provider,
        "data_stays_on_prem_for_inference": not external,
        "message": (
            "目前使用外部模型推論；提示與部分內容可能離開本機環境。"
            if external
            else "目前使用本機模型推論；知識與提問預設留在部署環境內。"
        ),
    }


def _pack_states() -> Dict[str, Dict[str, Any]]:
    status = module_status()
    labels = {
        ProductModule.BASE.value: "核心控制面",
        ProductModule.DOCUMENT_INTELLIGENCE.value: "文件增強解析",
        ProductModule.ENTERPRISE_CONNECT.value: "企業來源連接",
        ProductModule.KNOWLEDGE_COMPILER.value: "知識編譯（API-only）",
        ProductModule.AGENT_AUTOMATION.value: "自動入庫／審核",
    }
    out: Dict[str, Dict[str, Any]] = {}
    for key, enabled in status.items():
        out[key] = {
            "enabled": enabled,
            "state": "enabled" if enabled else "disabled",
            "label": labels.get(key, key),
        }
    # Certified connectors honesty
    out["certified_connectors"] = {
        "enabled": True,
        "state": "enabled",
        "label": "已認證來源",
        "items": ["nas_smb"],
        "not_certified": ["sharepoint", "google_drive"],
    }
    return out


@router.get("/bootstrap")
def experience_bootstrap(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Single bootstrap for UI navigation / honesty surface.
    """
    caps = _capabilities_for(current_user)

    # MKA: job modules + interaction capabilities（§5.4）
    job_modules: List[Dict[str, Any]] = []
    interaction_caps: Dict[str, bool] = {
        "voice": False, "camera": False, "qr": False, "offline": False,
    }
    default_job_home = "ask"
    try:
        from app.services.module_registry import get_module_registry
        registry = get_module_registry(db)
        available = registry.get_available_modules(
            tenant_id=current_user.tenant_id,
            user_roles=[current_user.role] if current_user.role else [],
            user_department_ids=[str(current_user.department_id)] if hasattr(current_user, "department_id") and current_user.department_id else [],
        )
        job_modules = available
        interaction_caps = registry.get_interaction_capabilities(current_user.tenant_id)
        if available:
            # 依第一個模組決定首頁
            first_key = available[0].get("module_key", "")
            default_job_home = f"module:{first_key}"
    except Exception:
        pass  # 誠實降級 — 不顯示假功能

    return {
        "product": {
            "name": "Enclave",
            "version_label": "2.0",
            "maturity": "pilot",
            "maturity_label": "Pilot／受控部署",
        },
        "user": {
            "id": str(current_user.id),
            "email": current_user.email,
            "full_name": current_user.full_name,
            "role": current_user.role,
            "tenant_id": str(current_user.tenant_id) if current_user.tenant_id else None,
            "is_superuser": bool(current_user.is_superuser),
        },
        "capabilities": caps,
        "default_home": "overview" if "admin_home" in caps else "ask",
        "packs": _pack_states(),
        "inference": _inference_boundary(db),
        "features": {
            "sso": False,
            "wiki_editor": False,
            "graph_production_write": False,
            "mobile_ga": False,
            "sharepoint_certified": False,
            "google_drive_certified": False,
            "review_queue_enabled": os.getenv("REVIEW_QUEUE_ENABLED", "true").lower() == "true",
        },
        # MKA §5.4: job modules + interaction capabilities
        "job_modules": job_modules,
        "default_job_home": default_job_home,
        "interaction_capabilities": interaction_caps,
    }
