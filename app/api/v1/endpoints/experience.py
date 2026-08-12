"""UX experience bootstrap — capabilities, packs, deployment boundary (UIUX 2.0)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.models.user import User
from app.services.product_license import ProductModule, module_status

router = APIRouter()

# Formal roles only — manager is not a UserRole
# 注意：此表必須與 frontend/src/navigation/capabilities.ts 的 ROLE_CAPS 保持一致；
# bootstrap 是能力唯一來源，前端本地表僅作 bootstrap 未載入時的 route-guard fallback。
_ROLE_CAPS: Dict[str, List[str]] = {
    "owner": [
        "ask", "browse_knowledge", "upload_documents", "manage_sources",
        "review_queue", "governance", "system_ops", "create_content",
        "view_usage", "admin_home", "field_work",
    ],
    "admin": [
        "ask", "browse_knowledge", "upload_documents", "manage_sources",
        "review_queue", "governance", "system_ops", "create_content",
        "view_usage", "admin_home", "field_work",
    ],
    "hr": [
        "ask", "browse_knowledge", "upload_documents", "create_content", "view_usage",
        "field_work",
    ],
    "employee": [
        "ask", "browse_knowledge", "create_content", "view_usage", "field_work",
    ],
    "viewer": [
        "ask", "browse_knowledge", "view_usage", "field_work",
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


def _filter_task_workspace_entries(
    entries: List[Dict[str, Any]], accessible_task_keys: set[str]
) -> List[Dict[str, Any]]:
    """Remove task links that the current user cannot start at runtime."""
    filtered: List[Dict[str, Any]] = []
    prefix = "/job/tasks/"
    for entry in entries:
        path = str(entry.get("path") or "")
        if path.startswith(prefix):
            task_key = path[len(prefix):].split("?", 1)[0].split("/", 1)[0]
            if task_key not in accessible_task_keys:
                continue
        filtered.append(entry)
    return filtered


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
    workspace_entries: List[Dict[str, Any]] = []
    job_role_assignments: List[Dict[str, Any]] = []
    active_job_role: Optional[Dict[str, Any]] = None
    interaction_caps: Dict[str, bool] = {
        "voice": False, "camera": False, "qr": False, "offline": False,
    }
    default_job_home = "job"
    needs_job_role_assignment = False
    try:
        from app.services.job_context import build_effective_job_context
        from app.services.module_registry import get_module_registry
        from app.services.module_router import get_module_router
        from app.services.mka_module_seed import (
            ensure_tenant_module_bindings,
            seed_canonical_modules,
            seed_canonical_task_definitions,
            seed_default_job_roles,
        )

        seed_canonical_modules(db)
        seed_canonical_task_definitions(db)
        # 新租戶模組改為 opt-in：只有 Demo Tenant 自動啟用全部正式模組，
        # 其他租戶由管理員在設定中心逐個啟用（避免新租戶工作台全攤平）。
        from app.models.tenant import Tenant

        tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
        if tenant is not None and tenant.name == "Demo Tenant":
            ensure_tenant_module_bindings(db, current_user.tenant_id)
        seed_default_job_roles(db, current_user.tenant_id)
        try:
            db.commit()
        except Exception:
            db.rollback()

        # EffectiveJobContext：安全角色（AuthorizationContext）＋業務職能（JobRole 指派）
        job_ctx = build_effective_job_context(db, current_user)
        job_role_assignments = [a.to_dict() for a in job_ctx.assignments]
        active_job_role = job_ctx.active_job_role.to_dict() if job_ctx.active_job_role else None
        needs_job_role_assignment = job_ctx.needs_job_role_assignment

        registry = get_module_registry(db)
        available = registry.get_available_modules(
            tenant_id=current_user.tenant_id,
            user_roles=list(job_ctx.security_roles),
            user_department_ids=list(job_ctx.department_ids),
            # 與 assert_module_access／chat／Task Engine 一致：依 active 職能過濾，
            # 避免 bootstrap 回傳使用者實際無權使用的模組（看得到、點進去 403）。
            job_role_keys=list(job_ctx.active_job_role_keys),
        )
        job_modules = available
        interaction_caps = registry.get_interaction_capabilities(current_user.tenant_id)

        if needs_job_role_assignment:
            # 無職能指派 → 空態，禁止回退成全部功能：
            # workspace_entries、job_modules、default_job_home 全部清空，
            # 與後端 runtime 路徑（chat／tasks／forms 的模組授權）一致。
            workspace_entries = []
            job_modules = []
        else:
            # 使用真實 AuthorizationContext（role_ids/department_ids 含祖先部門），
            # 不再維護 ad-hoc stub，避免與 chat 等 runtime 路徑的 ACL 不一致。
            from app.core.authorization import AuthorizationContext

            authz = AuthorizationContext.from_user(current_user)
            module_keys = job_ctx.active_module_keys or None
            workspace_entries = get_module_router(db=db).workspace_entries(authz, module_keys)
            from app.services.task_engine import get_task_engine

            accessible_task_keys = {
                definition.task_key
                for definition in get_task_engine(db).list_accessible_definitions(current_user)
            }
            workspace_entries = _filter_task_workspace_entries(
                workspace_entries, accessible_task_keys
            )
        if job_modules:
            first_key = job_modules[0].get("module_key", "")
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
        # 與前端 defaultHomePath 一致：admin → overview；現場人員 → job；其他 → ask
        "default_home": (
            "overview" if "admin_home" in caps
            else "job" if "field_work" in caps
            else "ask"
        ),
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
        "workspace_entries": workspace_entries,
        "job_role_assignments": job_role_assignments,
        "active_job_role": active_job_role,
        "needs_job_role_assignment": needs_job_role_assignment,
        "default_job_home": default_job_home,
        "interaction_capabilities": interaction_caps,
    }
