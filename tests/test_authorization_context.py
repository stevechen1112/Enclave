"""
Phase 0 — Authorization Context 單元測試

測試 AuthorizationContext 的正確性：
  - 從 User 建立 authz
  - 部門樹繼承
  - 快取鍵包含 policy_fingerprint
  - can_access_document 邏輯
  - 跨使用者快取隔離
"""
import uuid
import pytest
from app.core.authorization import AuthorizationContext, SearchScope


class TestAuthorizationContext:
    """AuthorizationContext 單元測試。"""

    def test_from_user_basic(self):
        """從 User 建立 authz — 基本欄位正確。"""
        # 模擬 User
        class MockUser:
            id = uuid.uuid4()
            tenant_id = uuid.uuid4()
            role = "employee"
            is_superuser = False
            department_id = None
            department = None

        user = MockUser()
        authz = AuthorizationContext.from_user(user)

        assert authz.tenant_id == user.tenant_id
        assert authz.subject_id == user.id
        assert authz.role_ids == ("employee",)
        assert authz.is_superuser is False
        assert authz.department_ids == ()

    def test_policy_collections_are_immutable_after_fingerprint(self):
        tenant_id = uuid.uuid4()
        subject_id = uuid.uuid4()
        authz = AuthorizationContext(
            tenant_id=tenant_id,
            subject_id=subject_id,
            role_ids=["viewer"],
        )
        fingerprint = authz.policy_fingerprint

        with pytest.raises(AttributeError):
            authz.role_ids.append("kb_admin")  # type: ignore[attr-defined]
        assert not authz.has_kb_admin
        assert authz.policy_fingerprint == fingerprint

    def test_from_user_with_department(self):
        """從 User 建立 authz — 包含部門。"""
        dept_id = uuid.uuid4()

        class MockDept:
            id = dept_id
            parent_id = None

        class MockUser:
            id = uuid.uuid4()
            tenant_id = uuid.uuid4()
            role = "hr"
            is_superuser = False
            department_id = dept_id
            department = MockDept()

        user = MockUser()
        authz = AuthorizationContext.from_user(user)

        assert dept_id in authz.department_ids

    def test_from_user_with_parent_department(self):
        """從 User 建立 authz — 包含祖先部門。"""
        parent_dept_id = uuid.uuid4()
        child_dept_id = uuid.uuid4()

        class MockParentDept:
            id = parent_dept_id
            parent_id = None

        class MockChildDept:
            id = child_dept_id
            parent_id = parent_dept_id
            parent = MockParentDept()

        class MockUser:
            id = uuid.uuid4()
            tenant_id = uuid.uuid4()
            role = "admin"
            is_superuser = False
            department_id = child_dept_id
            department = MockChildDept()

        user = MockUser()
        authz = AuthorizationContext.from_user(user)

        assert child_dept_id in authz.department_ids
        assert parent_dept_id in authz.department_ids  # 祖先部門

    def test_policy_fingerprint_different_users(self):
        """不同使用者的 policy_fingerprint 不同。"""
        user_a = _make_mock_user(role="employee")
        user_b = _make_mock_user(role="admin")

        authz_a = AuthorizationContext.from_user(user_a)
        authz_b = AuthorizationContext.from_user(user_b)

        assert authz_a.policy_fingerprint != authz_b.policy_fingerprint

    def test_policy_fingerprint_same_user(self):
        """相同使用者相同參數的 policy_fingerprint 相同（確定性）。"""
        user = _make_mock_user(role="employee")

        authz_1 = AuthorizationContext.from_user(user, policy_revision=1)
        authz_2 = AuthorizationContext.from_user(user, policy_revision=1)

        assert authz_1.policy_fingerprint == authz_2.policy_fingerprint

    def test_policy_fingerprint_different_revision(self):
        """不同 policy_revision 的 fingerprint 不同。"""
        user = _make_mock_user(role="employee")

        authz_v1 = AuthorizationContext.from_user(user, policy_revision=1)
        authz_v2 = AuthorizationContext.from_user(user, policy_revision=2)

        assert authz_v1.policy_fingerprint != authz_v2.policy_fingerprint

    def test_cache_fragment_contains_fingerprint(self):
        """快取片段包含 policy_fingerprint。"""
        user = _make_mock_user(role="employee")
        authz = AuthorizationContext.from_user(user)

        fragment = authz.to_cache_fragment()
        assert "auth:" in fragment
        assert authz.policy_fingerprint in fragment

    def test_can_access_document_same_tenant(self):
        """同租戶文件可存取。"""
        tenant_id = uuid.uuid4()
        user = _make_mock_user(tenant_id=tenant_id, role="employee")
        authz = AuthorizationContext.from_user(user)

        assert authz.can_access_document(tenant_id, None) is True

    def test_can_access_document_different_tenant(self):
        """不同租戶文件不可存取。"""
        user = _make_mock_user(tenant_id=uuid.uuid4(), role="employee")
        authz = AuthorizationContext.from_user(user)

        assert authz.can_access_document(uuid.uuid4(), None) is False

    def test_can_access_document_superuser(self):
        """Superuser 可存取任何同租戶文件。"""
        tenant_id = uuid.uuid4()
        dept_id = uuid.uuid4()
        user = _make_mock_user(tenant_id=tenant_id, role="owner", is_superuser=True)
        authz = AuthorizationContext.from_user(user)

        assert authz.can_access_document(tenant_id, dept_id) is True

    def test_can_access_document_department_match(self):
        """同部門文件可存取。"""
        tenant_id = uuid.uuid4()
        dept_id = uuid.uuid4()

        class MockDept:
            id = dept_id
            parent_id = None

        user = _make_mock_user(tenant_id=tenant_id, role="employee", dept_id=dept_id, dept=MockDept())
        authz = AuthorizationContext.from_user(user)

        assert authz.can_access_document(tenant_id, dept_id) is True

    def test_can_access_document_department_mismatch(self):
        """不同部門文件不可存取。"""
        tenant_id = uuid.uuid4()
        user_dept = uuid.uuid4()
        doc_dept = uuid.uuid4()

        class MockDept:
            id = user_dept
            parent_id = None

        user = _make_mock_user(tenant_id=tenant_id, role="employee", dept_id=user_dept, dept=MockDept())
        authz = AuthorizationContext.from_user(user)

        assert authz.can_access_document(tenant_id, doc_dept) is False

    def test_frozen_immutable(self):
        """AuthorizationContext 是不可變的。"""
        user = _make_mock_user(role="employee")
        authz = AuthorizationContext.from_user(user)

        with pytest.raises(Exception):
            authz.tenant_id = uuid.uuid4()  # frozen dataclass


class TestSearchScope:
    """SearchScope 單元測試。"""

    def test_default_scope(self):
        """預設 scope 包含 wiki，不包含 graph。"""
        scope = SearchScope()
        assert scope.include_wiki is True
        assert scope.include_graph is False
        assert scope.kb_ids is None  # all KBs

    def test_restricted_scope(self):
        """限制 scope 到特定 KB 和文件類型。"""
        kb_id = uuid.uuid4()
        scope = SearchScope(
            kb_ids=[kb_id],
            document_types=["pdf", "docx"],
            include_wiki=False,
        )
        assert scope.kb_ids == [kb_id]
        assert scope.document_types == ["pdf", "docx"]
        assert scope.include_wiki is False


# ── Helpers ──

def _make_mock_user(
    tenant_id=None,
    role="employee",
    is_superuser=False,
    dept_id=None,
    dept=None,
):
    """建立模擬 User 物件。"""
    class MockUser:
        pass

    user = MockUser()
    user.id = uuid.uuid4()
    user.tenant_id = tenant_id or uuid.uuid4()
    user.role = role
    user.is_superuser = is_superuser
    user.department_id = dept_id
    user.department = dept
    return user
