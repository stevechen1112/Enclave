"""UX experience bootstrap — capabilities, packs, deployment boundary (UIUX 2.0)."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.models.user import User
from app.platform.packs import PackRegistry, PackTenantContext
from app.services.access_capabilities import ROLE_CAPABILITIES, capabilities_for_user
from app.services.product_license import ProductModule, module_status

router = APIRouter()
logger = logging.getLogger(__name__)

# Formal roles only — manager is not a UserRole.  This server-owned map is the
# only role-to-capability authority; the frontend deliberately has no copy.
_ROLE_CAPS = ROLE_CAPABILITIES


def _capabilities_for(user: User) -> list[str]:
    return capabilities_for_user(user)


def _filter_task_workspace_entries(
    entries: list[dict[str, Any]], accessible_task_keys: set[str]
) -> list[dict[str, Any]]:
    """Remove task links that the current user cannot start at runtime."""
    filtered: list[dict[str, Any]] = []
    prefix = "/job/tasks/"
    for entry in entries:
        path = str(entry.get("path") or "")
        if path.startswith(prefix):
            task_key = path[len(prefix) :].split("?", 1)[0].split("/", 1)[0]
            if task_key not in accessible_task_keys:
                continue
        filtered.append(entry)
    return filtered


def _primary_navigation(
    capabilities: list[str], ui_modules: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compose one ordered navigation decision for every frontend surface."""
    caps = set(capabilities)
    base = [
        {"to": "/overview", "label": "總覽", "capability": "home", "end": True},
        {"to": "/ask", "label": "問答", "capability": "ask"},
        {"to": "/knowledge", "label": "知識", "capability": "browse_knowledge"},
        {"to": "/governance", "label": "管理", "capability": "governance"},
        {"to": "/system", "label": "系統", "capability": "system_ops"},
    ]
    items = [item for item in base if item["capability"] in caps]
    module_items = [
        {"to": nav["to"], "label": nav["label"], "module": manifest["ui_key"]}
        for manifest in ui_modules
        for nav in manifest.get("navigation", [])
        if str(nav.get("to") or "").startswith("/") and nav.get("label")
    ]
    seen = {item["to"] for item in items}
    insert_at = 1 if items and items[0]["to"] == "/overview" else 0
    for item in module_items:
        if item["to"] in seen:
            continue
        items.insert(insert_at, item)
        insert_at += 1
        seen.add(item["to"])
    return items


def _default_home(
    capabilities: list[str],
    ui_modules: list[dict[str, Any]],
    primary_navigation: list[dict[str, Any]],
) -> str:
    """Choose a home only from the navigation already authorized by the server."""
    if "admin_home" in capabilities:
        return "overview"
    reachable = {str(item.get("to")) for item in primary_navigation}
    for manifest in ui_modules:
        candidate = str(manifest.get("default_home") or "")
        if candidate in reachable:
            return candidate.removeprefix("/")
    return "overview" if "home" in capabilities else "ask"


def _tenant_ui_manifests(
    registry: PackRegistry,
    *,
    db: Session,
    tenant_id: Any,
) -> list[dict[str, Any]]:
    """Serialize the same pack eligibility decision used by API and UI routes."""
    manifests: list[dict[str, Any]] = []
    for pack_key, ui_module in registry.enabled_ui_modules(
        context=PackTenantContext(tenant_id=tenant_id, db=db)
    ):
        manifests.append(
            {
                "pack_key": pack_key,
                "ui_key": ui_module.ui_key,
                "version": ui_module.ui_version,
                "module_key": ui_module.module_key,
                "route_keys": list(ui_module.route_keys),
                "required_capabilities": list(ui_module.required_capability_keys),
                "navigation": [dict(item) for item in ui_module.navigation],
                "bundle_key": ui_module.bundle_key,
                "default_home": ui_module.default_home,
            }
        )
    return manifests


def _inference_boundary(db: Session) -> dict[str, Any]:
    """Honest data-boundary signal for UI (local vs external model)."""
    try:
        from app.services.deployment_mode import resolve_runtime_profiles

        profiles = resolve_runtime_profiles(db)
        main_provider = str(
            (profiles.get("main") or {}).get("provider") or "ollama"
        ).lower()
    except Exception:  # noqa: BLE001 - bootstrap reports a conservative boundary
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


def _pack_states() -> dict[str, dict[str, Any]]:
    status = module_status()
    from app.gateway.runtime_health import get_runtime_health_snapshot

    runtime = get_runtime_health_snapshot() or {}
    runtime_packs = runtime.get("packs") or {}
    labels = {
        ProductModule.BASE.value: "核心控制面",
        ProductModule.DOCUMENT_INTELLIGENCE.value: "文件增強解析",
        ProductModule.ENTERPRISE_CONNECT.value: "企業來源連接",
        ProductModule.KNOWLEDGE_COMPILER.value: "知識編譯（API-only）",
        ProductModule.AGENT_AUTOMATION.value: "自動入庫／審核",
    }
    out: dict[str, dict[str, Any]] = {}
    for key, enabled in status.items():
        verified = runtime_packs.get(key) or {}
        state = verified.get("state")
        if not state:
            state = "disabled" if not enabled else "unavailable"
        out[key] = {
            "enabled": enabled,
            "available": bool(verified.get("available", False)),
            "state": state,
            "label": labels.get(key, key),
            "message": (
                "已通過執行環境健康探測"
                if state == "enabled"
                else "已設定但執行服務目前不可用"
                if enabled
                else "未啟用"
            ),
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
    db: Session = Depends(get_db),  # noqa: B008 - FastAPI dependency declaration
    current_user: User = Depends(get_current_active_user),  # noqa: B008
) -> dict[str, Any]:
    """
    Single bootstrap for UI navigation / honesty surface.
    """
    caps = _capabilities_for(current_user)

    # MKA: job modules + interaction capabilities（§5.4）
    job_modules: list[dict[str, Any]] = []
    workspace_entries: list[dict[str, Any]] = []
    job_role_assignments: list[dict[str, Any]] = []
    active_job_role: dict[str, Any] | None = None
    interaction_caps: dict[str, bool] = {
        "voice": False,
        "camera": False,
        "qr": False,
        "offline": False,
    }
    default_job_home = "job"
    needs_job_role_assignment = False
    is_demo_tenant = False
    ui_modules: list[dict[str, Any]] = []
    from app.composition.packs import build_pack_registry

    pack_registry = build_pack_registry()
    from app.composition.pack_surfaces import resolve_pack_permissions

    pack_permissions = list(resolve_pack_permissions(pack_registry, current_user))
    from app.gateway.runtime_health import get_runtime_health_snapshot
    from app.services.capability_catalog import build_capability_catalog

    try:
        if not pack_registry.is_deployed("mka"):
            raise LookupError("MKA pack is not deployed")
        # Bootstrap is a pure read. Canonical MKA data and tenant bindings are
        # provisioned by the explicit pack lifecycle hook/demo setup service.
        from app.models.tenant import Tenant
        from app.services.job_context import build_effective_job_context
        from app.services.module_registry import get_module_registry
        from app.services.module_router import get_module_router

        tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
        from app.demo.manifest import DEMO_TENANT_ID

        if tenant is not None and tenant.is_demo and tenant.id == DEMO_TENANT_ID:
            is_demo_tenant = True

        if not pack_registry.is_enabled_for_tenant(
            "mka",
            context=PackTenantContext(tenant_id=current_user.tenant_id, db=db),
        ):
            raise LookupError("MKA pack is not enabled for tenant")

        # EffectiveJobContext combines security roles and business job roles.
        job_ctx = build_effective_job_context(db, current_user)
        job_role_assignments = [a.to_dict() for a in job_ctx.assignments]
        active_job_role = (
            job_ctx.active_job_role.to_dict() if job_ctx.active_job_role else None
        )
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
            workspace_entries = get_module_router(db=db).workspace_entries(
                authz, module_keys
            )
            from app.services.task_engine import get_task_engine

            accessible_task_keys = {
                definition.task_key
                for definition in get_task_engine(db).list_accessible_definitions(
                    current_user
                )
            }
            workspace_entries = _filter_task_workspace_entries(
                workspace_entries, accessible_task_keys
            )
        if job_modules:
            first_key = job_modules[0].get("module_key", "")
            default_job_home = f"module:{first_key}"
        ui_modules = _tenant_ui_manifests(
            pack_registry, db=db, tenant_id=current_user.tenant_id
        )
    except LookupError:
        # Expected for a deployment- or tenant-disabled pack.
        job_modules = []
        workspace_entries = []
        job_role_assignments = []
        active_job_role = None
        interaction_caps = {
            "voice": False,
            "camera": False,
            "qr": False,
            "offline": False,
        }
        ui_modules = []
    except Exception:
        # Never return a partially assembled workspace after a DB or pack error.
        logger.exception("MKA experience bootstrap degraded closed")
        job_modules = []
        workspace_entries = []
        job_role_assignments = []
        active_job_role = None
        interaction_caps = {
            "voice": False,
            "camera": False,
            "qr": False,
            "offline": False,
        }
        ui_modules = []

    field_work_available = any(
        "mka.job.home" in manifest.get("route_keys", []) for manifest in ui_modules
    )
    if field_work_available and "field_work" not in caps:
        caps.append("field_work")
    capability_catalog = build_capability_catalog(
        db,
        tenant_id=current_user.tenant_id,
        pack_registry=pack_registry,
        runtime_snapshot=get_runtime_health_snapshot(),
        user_permissions=set(pack_permissions),
        accessible_modules_by_pack={
            "mka": {
                str(module.get("module_key"))
                for module in job_modules
                if module.get("module_key")
            }
        },
    )
    primary_navigation = _primary_navigation(caps, ui_modules)
    default_home = _default_home(caps, ui_modules, primary_navigation)

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
            "tenant_id": str(current_user.tenant_id)
            if current_user.tenant_id
            else None,
            "is_superuser": bool(current_user.is_superuser),
        },
        "capabilities": caps,
        # The same server decision drives login redirect, shell and route guards.
        "default_home": default_home,
        "primary_navigation": primary_navigation,
        "packs": _pack_states(),
        "inference": _inference_boundary(db),
        "features": {
            "sso": False,
            "wiki_editor": False,
            "graph_production_write": False,
            "mobile_ga": False,
            "sharepoint_certified": False,
            "google_drive_certified": False,
            "review_queue_enabled": os.getenv("REVIEW_QUEUE_ENABLED", "true").lower()
            == "true",
        },
        "demo_mode": is_demo_tenant,
        # MKA §5.4: job modules + interaction capabilities
        "job_modules": job_modules,
        "workspace_entries": workspace_entries,
        "job_role_assignments": job_role_assignments,
        "active_job_role": active_job_role,
        "needs_job_role_assignment": needs_job_role_assignment,
        "default_job_home": default_job_home,
        "interaction_capabilities": interaction_caps,
        "ui_modules": ui_modules,
        "pack_permissions": pack_permissions,
        "capability_catalog": capability_catalog,
    }
