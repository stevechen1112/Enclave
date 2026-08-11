"""
Phase 0 — Authorization Context & Policy Enforcement

定義統一的授權上下文（AuthorizationContext），用於：
  - 檢索前 ACL 過濾（PEP — Policy Enforcement Point）
  - 快取鍵（包含 policy fingerprint 防止跨使用者快取洩漏）
  - 稽核記錄（誰在什麼政策版本下執行了什麼操作）

Deny precedence 公式（ADR-004）：
  ALLOW = tenant_match
          AND kb_policy_allows
          AND department_policy_allows
          AND source_acl_allows_if_present
          AND resource_not_tombstoned
          AND policy_revision_is_current
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import List, Optional, Set
from uuid import UUID


@dataclass(frozen=True)
class AuthorizationContext:
    """
    不可變授權上下文 — 在請求入口建立，傳遞到所有下游。

    設計原則：
      - frozen=True：建立後不可修改，防止中間件意外變更
      - 包含 policy_fingerprint：快取鍵的一部分，權限變更時自動失效
      - 包含 department_path：支援部門樹繼承（祖先部門可見子部門文件）
    """

    tenant_id: UUID
    subject_id: UUID                          # user ID
    role_ids: List[str] = field(default_factory=list)   # owner, admin, hr, employee, viewer
    department_ids: List[UUID] = field(default_factory=list)  # 使用者所屬部門 + 祖先部門
    group_ids: List[UUID] = field(default_factory=list)       # 外部群組映射
    is_superuser: bool = False
    policy_revision: int = 1
    policy_fingerprint: str = ""

    def __post_init__(self):
        """計算 policy_fingerprint（若未提供）。"""
        if not self.policy_fingerprint:
            fingerprint = self._compute_fingerprint()
            object.__setattr__(self, 'policy_fingerprint', fingerprint)

    def _compute_fingerprint(self) -> str:
        """基於授權參數計算確定性指紋。"""
        parts = [
            str(self.tenant_id),
            str(self.subject_id),
            ",".join(sorted(self.role_ids)),
            ",".join(str(d) for d in sorted(self.department_ids)),
            ",".join(str(g) for g in sorted(self.group_ids)),
            str(self.policy_revision),
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_cache_fragment(self) -> str:
        """產生快取鍵片段（不含 query/mode/top_k — 由呼叫方組合）。"""
        return f"auth:{self.policy_fingerprint}"

    def to_sql_acl_predicate(self) -> str:
        """
        產生 SQL ACL 過濾條件（用於向量/關鍵字檢索的 WHERE 子句）。

        注意：此方法產生的是 SQL 片段，需由呼叫方安全地組合進查詢。
        實際使用時建議用參數化查詢而非字串拼接。
        """
        # 基本條件：tenant match + not tombstoned
        conditions = [
            "documents.tenant_id = :auth_tenant_id",
            "documents.tombstoned_at IS NULL",
        ]

        # 非 kb_admin 需部門過濾
        if not self.has_kb_admin:
            if self.department_ids:
                dept_placeholders = ", ".join(
                    f":auth_dept_{i}" for i in range(len(self.department_ids))
                )
                conditions.append(
                    f"(documents.department_id IS NULL "
                    f"OR documents.department_id IN ({dept_placeholders}))"
                )
            else:
                conditions.append("documents.department_id IS NULL")

        return " AND ".join(conditions)

    def to_sql_params(self) -> dict:
        """產生對應 to_sql_acl_predicate() 的參數 dict。"""
        params = {"auth_tenant_id": self.tenant_id}
        for i, dept_id in enumerate(self.department_ids):
            params[f"auth_dept_{i}"] = dept_id
        return params

    @property
    def has_kb_admin(self) -> bool:
        """
        租戶級 KB 管理 bypass。

        計畫不變量：唯一 bypass = is_superuser 或明確 role `kb_admin`。
        owner/admin/hr 不再自動全租戶可見文件。
        """
        return self.is_superuser or "kb_admin" in self.role_ids

    def can_access_document(self, doc_tenant_id: UUID, doc_department_id: Optional[UUID]) -> bool:
        """檢查是否可存取特定文件（應用層授權檢查；含祖先部門）。"""
        if doc_tenant_id != self.tenant_id:
            return False
        if self.has_kb_admin:
            return True
        if doc_department_id is None:
            return True
        if not self.department_ids:
            return False
        return doc_department_id in self.department_ids

    def department_filter_ids(self) -> Optional[List[UUID]]:
        """
        供 SQL 過濾使用。

        回傳：
          - None：不套部門過濾（kb_admin / superuser）
          - []：僅允許 department_id IS NULL
          - [..]：允許 NULL 或 IN 列表（含祖先）
        """
        if self.has_kb_admin:
            return None
        return list(self.department_ids)

    @classmethod
    def from_user(
        cls,
        user,  # app.models.user.User
        policy_revision: int = 1,
    ) -> "AuthorizationContext":
        """
        從 User ORM 物件建立 AuthorizationContext。

        自動解析部門樹（包含祖先部門）。
        """
        role_ids = [user.role] if user.role else ["viewer"]

        # 解析部門路徑（使用者部門 + 所有祖先）
        department_ids: List[UUID] = []
        if user.department_id:
            department_ids.append(user.department_id)
            # 向上走訪祖先部門；深度上限防止部門樹成環時請求卡死
            current = getattr(user, "department", None)
            seen: Set[UUID] = {user.department_id}
            max_depth = 32
            while (
                current
                and current.parent_id
                and current.parent_id not in seen
                and len(department_ids) < max_depth
            ):
                department_ids.append(current.parent_id)
                seen.add(current.parent_id)
                current = current.parent

        return cls(
            tenant_id=user.tenant_id,
            subject_id=user.id,
            role_ids=role_ids,
            department_ids=department_ids,
            is_superuser=bool(user.is_superuser),
            policy_revision=policy_revision,
        )


@dataclass(frozen=True)
class SearchScope:
    """
    檢索範圍 — 限制搜尋的 KB、文件類型、來源系統等。

    與 AuthorizationContext 分離：AuthZ 回答「誰」，Scope 回答「搜什麼」。
    """

    kb_ids: Optional[List[UUID]] = None          # None = all accessible KBs
    document_types: Optional[List[str]] = None   # pdf, docx, txt, ...
    source_systems: Optional[List[str]] = None   # google_drive, sharepoint, ...
    date_range: Optional[tuple] = None           # (start, end)
    include_wiki: bool = True
    include_graph: bool = False
