"""
P1-4：職能模組 Router — 依使用者職能路由到對應模組。

稽核文件 §10 P1：
- 職能模組 Router
- 由 Enclave 掌控身分、權限、來源、表單與審核

製造業常見職能：
- 採購（procurement）
- 業務（sales）
- 倉管（warehouse）
- 生產（production）
- 品保（quality）
- 財務（finance）
- 人資（hr）

Router 依使用者角色／部門，決定可用的模組、表單、工具與檢索範圍。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class ModuleConfig:
    """職能模組設定。"""
    name: str
    label: str
    description: str = ""
    # 可用的表單
    forms: List[str] = field(default_factory=list)
    # 可用的工具
    tools: List[str] = field(default_factory=list)
    # 檢索範圍（metadata filter）
    retrieval_scope: Dict[str, List[str]] = field(default_factory=dict)
    # 需要的角色
    required_roles: List[str] = field(default_factory=list)
    # 需要的部門
    required_departments: List[str] = field(default_factory=list)
    # 預設簽核角色
    approver_roles: List[str] = field(default_factory=list)


class ModuleRouter:
    """職能模組 Router。

    依 AuthorizationContext 的角色／部門，決定可用的模組。
    """

    def __init__(self):
        self._modules: Dict[str, ModuleConfig] = {}
        self._register_defaults()

    def register(self, module: ModuleConfig) -> None:
        self._modules[module.name] = module
        logger.info(f"Registered module: {module.name}")

    def get_module(self, name: str) -> Optional[ModuleConfig]:
        return self._modules.get(name)

    def list_modules(self) -> List[str]:
        return sorted(self._modules.keys())

    def get_available_modules(
        self,
        authz: Any,
    ) -> List[ModuleConfig]:
        """取得使用者可用的模組列表。

        Args:
            authz: AuthorizationContext

        Returns:
            可用模組列表
        """
        if authz is None:
            return []

        from app.config import settings
        if not settings.MODULE_ROUTER_ENABLED:
            # 未啟用時回傳全部模組（不限制）
            return list(self._modules.values())

        available = []
        user_roles = getattr(authz, "roles", []) or []
        user_dept = getattr(authz, "department_id", None)

        for module in self._modules.values():
            # 檢查角色
            if module.required_roles:
                if not any(r in user_roles for r in module.required_roles):
                    continue

            # 檢查部門
            if module.required_departments:
                if str(user_dept) not in module.required_departments:
                    continue

            available.append(module)

        return available

    def get_retrieval_scope(
        self,
        module_name: str,
        authz: Any,
    ) -> Dict[str, List[str]]:
        """取得模組的檢索範圍。

        Args:
            module_name: 模組名稱
            authz: AuthorizationContext

        Returns:
            metadata filter dict（用於 kb_retrieval.search 的 filter_dict）
        """
        module = self.get_module(module_name)
        if module is None:
            return {}

        # 合併模組 scope 與使用者 ACL
        scope = dict(module.retrieval_scope)

        # 使用者 ACL 進一步限制（不擴張）
        if authz:
            user_dept = getattr(authz, "department_id", None)
            if user_dept:
                # 若模組有指定部門範圍，取交集
                if "department" in scope:
                    if str(user_dept) not in scope["department"]:
                        scope["department"] = [str(user_dept)]  # 限制到使用者部門
                # 否則不額外限制（模組決定）

        return scope

    def get_forms_for_module(self, module_name: str) -> List[str]:
        """取得模組可用的表單。"""
        module = self.get_module(module_name)
        return module.forms if module else []

    def get_tools_for_module(self, module_name: str) -> List[str]:
        """取得模組可用的工具。"""
        module = self.get_module(module_name)
        return module.tools if module else []

    def _register_defaults(self) -> None:
        """註冊製造業預設模組。"""
        # 採購模組
        self.register(ModuleConfig(
            name="procurement",
            label="採購管理",
            description="採購單建立、供應商管理、採購歷史查詢",
            forms=["purchase_order", "quote"],
            tools=["kb_search", "document_list", "create_purchase_order"],
            retrieval_scope={"category": ["採購", "供應商", "採購單"]},
            required_roles=["procurement", "finance", "owner"],
            approver_roles=["owner", "finance"],
        ))

        # 業務模組
        self.register(ModuleConfig(
            name="sales",
            label="業務管理",
            description="報價單建立、客戶管理、訂單追蹤",
            forms=["quote"],
            tools=["kb_search", "document_list", "create_quote"],
            retrieval_scope={"category": ["業務", "客戶", "報價", "訂單"]},
            required_roles=["sales", "owner"],
            approver_roles=["owner", "sales"],
        ))

        # 倉管模組
        self.register(ModuleConfig(
            name="warehouse",
            label="倉儲管理",
            description="庫存查詢、入出庫管理、料號查詢",
            forms=["inventory_check"],
            tools=["kb_search", "document_list", "check_inventory"],
            retrieval_scope={"category": ["倉儲", "庫存", "料號", "入出庫"]},
            required_roles=["warehouse", "production", "owner"],
            approver_roles=["owner", "warehouse"],
        ))

        # 生產模組
        self.register(ModuleConfig(
            name="production",
            label="生產管理",
            description="工單管理、生產排程、SOP 查詢",
            forms=["work_order"],
            tools=["kb_search", "document_list", "create_work_order"],
            retrieval_scope={"category": ["生產", "工單", "SOP", "製程"]},
            required_roles=["production", "owner"],
            approver_roles=["owner", "production"],
        ))

        # 品保模組
        self.register(ModuleConfig(
            name="quality",
            label="品保管理",
            description="品質檢驗、異常處理、SOP 查詢",
            forms=["quality_check", "nonconformance_report"],
            tools=["kb_search", "document_list", "create_quality_check"],
            retrieval_scope={"category": ["品保", "品質", "檢驗", "異常", "SOP"]},
            required_roles=["quality", "production", "owner"],
            approver_roles=["owner", "quality"],
        ))

        # 財務模組
        self.register(ModuleConfig(
            name="finance",
            label="財務管理",
            description="報價審核、採購審核、成本分析",
            forms=["quote", "purchase_order"],
            tools=["kb_search", "document_list", "approve_form"],
            retrieval_scope={"category": ["財務", "報價", "採購", "成本", "稅務"]},
            required_roles=["finance", "owner"],
            approver_roles=["owner"],
        ))

        # 人資模組
        self.register(ModuleConfig(
            name="hr",
            label="人資管理",
            description="員工資料、薪資、考核、SOP",
            forms=["leave_request", "performance_review"],
            tools=["kb_search", "document_list"],
            retrieval_scope={"category": ["人資", "員工", "薪資", "考核", "SOP"]},
            required_roles=["hr", "owner"],
            approver_roles=["owner", "hr"],
        ))


# ── 單例 ──

_router: Optional[ModuleRouter] = None


def get_module_router() -> ModuleRouter:
    global _router
    if _router is None:
        _router = ModuleRouter()
    return _router