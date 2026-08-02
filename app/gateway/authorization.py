"""
Phase 1 — Gateway Authorization (PDP/PEP)

Policy Decision Point & Policy Enforcement Point。
在 Gateway 層執行授權決策，確保所有下游請求都經過 ACL 過濾。

Deny precedence（ADR-004）：
  ALLOW = tenant_match
          AND kb_policy_allows
          AND department_policy_allows
          AND source_acl_allows_if_present
          AND resource_not_tombstoned
          AND policy_revision_is_current
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.authorization import AuthorizationContext

logger = logging.getLogger(__name__)


@dataclass
class PolicyDecision:
    """單一授權決策。"""
    allowed: bool
    reason: str
    policy_revision: int
    matched_rules: List[str]


class GatewayAuthorizer:
    """
    Gateway 層授權引擎。

    職責：
      1. 從請求中提取 AuthorizationContext
      2. 對每個下游請求執行 deny precedence 檢查
      3. 產生 policy snapshot 供稽核
    """

    def __init__(self):
        self._deny_cache: Dict[str, set] = {}  # resource_id → denied subject_ids

    def authorize_search(
        self,
        authz: AuthorizationContext,
        scope: Optional[Dict[str, Any]] = None,
    ) -> PolicyDecision:
        """
        授權檢索請求。

        目前實作：依 AuthorizationContext 的 tenant/department 判斷。
        Phase 3 擴充：加入來源 ACL 檢查。
        """
        matched = []

        # 1. Tenant match（由 JWT 保證，此處為防禦性檢查）
        if not authz.tenant_id:
            return PolicyDecision(
                allowed=False,
                reason="missing_tenant",
                policy_revision=authz.policy_revision,
                matched_rules=[],
            )
        matched.append("tenant_match")

        # 2. KB policy
        if scope and scope.get("kb_ids"):
            kb_allowed = self._check_kb_access(authz, scope.get("kb_ids"))
            if not kb_allowed:
                return PolicyDecision(
                    allowed=False,
                    reason="kb_policy_denied",
                    policy_revision=authz.policy_revision,
                    matched_rules=matched,
                )
            matched.append("kb_policy:scoped_allow")
        else:
            matched.append("kb_policy:default_allow")

        # 3. Department policy
        if authz.has_kb_admin:
            matched.append("department_policy:kb_admin_bypass")
        elif authz.department_ids:
            matched.append("department_policy:scoped")
        else:
            matched.append("department_policy:no_department")

        # 4. Source ACL — connector 來源必須有 mapped principal（fail-closed）
        if scope and scope.get("source_systems"):
            if self._check_source_acl(authz, scope.get("source_systems")):
                matched.append("source_acl:allowed")
            else:
                return PolicyDecision(
                    allowed=False,
                    reason="source_acl_denied",
                    policy_revision=authz.policy_revision,
                    matched_rules=matched,
                )
        else:
            matched.append("source_acl:not_applicable")

        # 5. Resource tombstone（由檢索層 SQL 過濾）
        matched.append("tombstone:sql_filtered")

        # 6. Policy revision（由 AuthorizationContext 保證）
        matched.append(f"policy_revision:{authz.policy_revision}")

        return PolicyDecision(
            allowed=True,
            reason="all_checks_passed",
            policy_revision=authz.policy_revision,
            matched_rules=matched,
        )

    def authorize_ingest(
        self,
        authz: AuthorizationContext,
        kb_id: UUID,
    ) -> PolicyDecision:
        """授權文件擷取請求。"""
        # 只有 admin/owner 可擷取
        allowed_roles = {"owner", "admin"}
        if authz.is_superuser or any(r in allowed_roles for r in authz.role_ids):
            return PolicyDecision(
                allowed=True,
                reason="admin_or_owner",
                policy_revision=authz.policy_revision,
                matched_rules=["role:admin_or_owner"],
            )
        return PolicyDecision(
            allowed=False,
            reason="insufficient_role",
            policy_revision=authz.policy_revision,
            matched_rules=[],
        )

    def authorize_delete(
        self,
        authz: AuthorizationContext,
        resource_type: str,
        resource_id: str,
    ) -> PolicyDecision:
        """授權刪除請求。"""
        return self.authorize_ingest(authz, UUID(resource_id) if resource_id else UUID(int=0))

    def add_deny_entry(self, resource_id: str, subject_id: UUID, tenant_id: Optional[UUID] = None):
        """Immediately deny one subject for a resource (memory + persistent)."""
        if resource_id not in self._deny_cache:
            self._deny_cache[resource_id] = set()
        self._deny_cache[resource_id].add(subject_id)
        if tenant_id:
            try:
                from app.db.session import SessionLocal
                from app.services.policy_deny import add_deny
                db = SessionLocal()
                try:
                    add_deny(db, tenant_id, "document", resource_id, subject_id, reason="revoked")
                    db.commit()
                finally:
                    db.close()
            except Exception as exc:
                logger.warning("Failed to persist deny entry: %s", exc)
        logger.info("Deny entry added: resource=%s, subject=%s", resource_id, subject_id)

    def deny_resource(self, resource_id: str, tenant_id: Optional[UUID] = None, reason: str = "revoked"):
        """Deny-first: block ALL subjects for this resource until cleared."""
        from app.services.policy_deny import RESOURCE_WIDE_DENY_SUBJECT, add_resource_deny

        if resource_id not in self._deny_cache:
            self._deny_cache[resource_id] = set()
        self._deny_cache[resource_id].add(RESOURCE_WIDE_DENY_SUBJECT)
        if tenant_id:
            try:
                from app.db.session import SessionLocal
                db = SessionLocal()
                try:
                    add_resource_deny(db, tenant_id, "document", resource_id, reason=reason)
                    db.commit()
                finally:
                    db.close()
            except Exception as exc:
                logger.warning("Failed to persist resource deny: %s", exc)
        logger.info("Resource-wide deny added: resource=%s reason=%s", resource_id, reason)

    def clear_resource_deny(self, resource_id: str):
        """Clear memory + persistent denies for a resource (e.g. re-ingest after revoke)."""
        self._deny_cache.pop(resource_id, None)
        try:
            from app.db.session import SessionLocal
            from app.services.policy_deny import clear_resource_denies
            db = SessionLocal()
            try:
                clear_resource_denies(db, "document", resource_id)
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.warning("Failed to clear resource deny: %s", exc)

    def remove_deny_entry(self, resource_id: str, subject_id: UUID):
        if resource_id in self._deny_cache:
            self._deny_cache[resource_id].discard(subject_id)
        try:
            from app.db.session import SessionLocal
            from app.services.policy_deny import remove_deny
            db = SessionLocal()
            try:
                remove_deny(db, "document", resource_id, subject_id)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

    def is_denied(self, resource_id: str, subject_id: UUID) -> bool:
        from app.services.policy_deny import RESOURCE_WIDE_DENY_SUBJECT

        denied_subjects = self._deny_cache.get(resource_id, set())
        if subject_id in denied_subjects or RESOURCE_WIDE_DENY_SUBJECT in denied_subjects:
            return True
        try:
            from app.db.session import SessionLocal
            from app.services.policy_deny import is_denied
            db = SessionLocal()
            try:
                return is_denied(db, "document", resource_id, subject_id)
            finally:
                db.close()
        except Exception as exc:
            # Deny-set 查詢失敗 → fail closed（視為已撤權）
            logger.warning("Deny-set lookup failed, fail closed: %s", exc)
            return True

    def authorize_source_record(
        self,
        authz: AuthorizationContext,
        source_system: Optional[str],
        source_record_id: Optional[str],
        db=None,
    ) -> bool:
        """Object-level connector ACL. Missing IDs → fail closed."""
        from app.services.resource_policy import get_resource_policy
        if db is not None:
            return get_resource_policy().authorize_source_record(
                db, authz, source_system=source_system, source_record_id=source_record_id,
            )
        try:
            from app.db.session import SessionLocal
            session = SessionLocal()
            try:
                return get_resource_policy().authorize_source_record(
                    session, authz,
                    source_system=source_system,
                    source_record_id=source_record_id,
                )
            finally:
                session.close()
        except Exception as exc:
            logger.warning("Source ACL check failed, fail closed: %s", exc)
            return False

    def _check_source_acl(self, authz: AuthorizationContext, source_systems: list) -> bool:
        """
        Scope-level gate when search requests connector domains.
        Still fail-closed without mapped principal; object-level checks happen post-filter.
        """
        if authz.has_kb_admin:
            return True
        if not source_systems:
            return True
        try:
            from app.db.session import SessionLocal
            from app.models.connector import ExternalPrincipal
            db = SessionLocal()
            try:
                principal = (
                    db.query(ExternalPrincipal.id)
                    .filter(
                        ExternalPrincipal.tenant_id == authz.tenant_id,
                        ExternalPrincipal.mapped_subject_id == authz.subject_id,
                    )
                    .first()
                )
                return principal is not None
            finally:
                db.close()
        except Exception as exc:
            logger.warning("Source ACL scope check failed, fail closed: %s", exc)
            return False

    def _check_kb_access(self, authz: AuthorizationContext, kb_ids: list) -> bool:
        """Check KB membership for scoped search."""
        if authz.has_kb_admin:
            return True
        try:
            from app.db.session import SessionLocal
            from app.models.knowledge_base import KnowledgeBaseMember
            from uuid import UUID as _UUID

            db = SessionLocal()
            try:
                for kb_id in kb_ids:
                    kb_uuid = _UUID(str(kb_id))
                    member = (
                        db.query(KnowledgeBaseMember)
                        .filter(
                            KnowledgeBaseMember.kb_id == kb_uuid,
                            KnowledgeBaseMember.subject_id == authz.subject_id,
                            KnowledgeBaseMember.effect == "allow",
                        )
                        .first()
                    )
                    if member:
                        return True
                    if authz.department_ids:
                        dept_member = (
                            db.query(KnowledgeBaseMember)
                            .filter(
                                KnowledgeBaseMember.kb_id == kb_uuid,
                                KnowledgeBaseMember.subject_type == "department",
                                KnowledgeBaseMember.subject_id.in_(authz.department_ids),
                                KnowledgeBaseMember.effect == "allow",
                            )
                            .first()
                        )
                        if dept_member:
                            return True
                return False
            finally:
                db.close()
        except Exception as exc:
            logger.warning("KB policy check failed, fail closed: %s", exc)
            return False


_authorizer_singleton: Optional[GatewayAuthorizer] = None


def get_gateway_authorizer() -> GatewayAuthorizer:
    """Process-wide authorizer so deny cache stays consistent across retrievers."""
    global _authorizer_singleton
    if _authorizer_singleton is None:
        _authorizer_singleton = GatewayAuthorizer()
    return _authorizer_singleton
