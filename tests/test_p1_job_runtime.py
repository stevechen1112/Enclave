"""Phase 1 職能 runtime 契約測試：EffectiveJobContext、職能切換、模組 allowlist、config merge。"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationship targets
from app.db.base_class import Base
from app.models.mka import JobModule, JobRole, TenantModuleBinding, UserJobRoleAssignment
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.services.job_context import (
    ModuleAccessDenied,
    assert_form_access,
    assert_module_access,
    build_effective_job_context,
    set_active_job_role,
)
from app.services.module_registry import ModuleRegistry


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Tenant.__table__,
        Department.__table__,
        User.__table__,
        JobModule.__table__,
        TenantModuleBinding.__table__,
        JobRole.__table__,
        UserJobRoleAssignment.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db, role="employee"):
    tenant = Tenant(id=uuid.uuid4(), name=f"tenant-{uuid.uuid4()}")
    db.add(tenant)
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"{uuid.uuid4()}@test.local",
        hashed_password="x",
        role=role,
    )
    db.add(user)
    db.commit()
    return tenant, user


def _role(db, tenant, key, name, modules):
    r = JobRole(
        id=uuid.uuid4(), tenant_id=tenant.id, role_key=key, name=name,
        default_module_keys=modules, active=True,
    )
    db.add(r)
    db.commit()
    return r


def _assign(db, tenant, user, role, primary=False):
    a = UserJobRoleAssignment(
        id=uuid.uuid4(), tenant_id=tenant.id, user_id=user.id,
        job_role_id=role.id, is_primary=primary, active=True,
    )
    db.add(a)
    db.commit()
    return a


def _module(db, key, allowed_job_role_keys=None, allowed_roles=None, tenant_id=None):
    m = JobModule(
        id=uuid.uuid4(), module_key=key, tenant_id=tenant_id, name=key,
        status="enabled", allowed_roles=allowed_roles or [],
        allowed_job_role_keys=allowed_job_role_keys or [],
        form_definition_ids=[],
    )
    db.add(m)
    db.commit()
    return m


def _bind(db, tenant, key, enabled=True):
    b = TenantModuleBinding(
        id=uuid.uuid4(), tenant_id=tenant.id, module_key=key, enabled=enabled,
        config_version=0,  # 明確從 0 起算，避免 server_default 造成版本不確定
    )
    db.add(b)
    db.commit()
    return b


class TestEffectiveJobContext:
    def test_no_assignment_needs_assignment(self, db):
        tenant, user = _user(db)
        ctx = build_effective_job_context(db, user)
        assert ctx.needs_job_role_assignment is True
        assert ctx.active_job_role is None
        assert ctx.active_module_keys == []
        assert ctx.active_job_role_keys == []

    def test_active_role_prefers_persisted_over_primary(self, db):
        tenant, user = _user(db)
        sales = _role(db, tenant, "sales", "業務", ["sales_quote"])
        field = _role(db, tenant, "field", "現場", ["incident_handover"])
        _assign(db, tenant, user, sales, primary=True)
        _assign(db, tenant, user, field, primary=False)
        user.active_job_role_id = field.id
        db.commit()

        ctx = build_effective_job_context(db, user)
        assert ctx.needs_job_role_assignment is False
        assert ctx.active_job_role is not None
        assert ctx.active_job_role.role_key == "field"
        assert ctx.active_module_keys == ["incident_handover"]

    def test_active_role_falls_back_to_primary(self, db):
        tenant, user = _user(db)
        sales = _role(db, tenant, "sales", "業務", ["sales_quote"])
        _assign(db, tenant, user, sales, primary=True)
        ctx = build_effective_job_context(db, user)
        assert ctx.active_job_role.role_key == "sales"

    def test_disabled_role_assignment_ignored(self, db):
        tenant, user = _user(db)
        sales = _role(db, tenant, "sales", "業務", ["sales_quote"])
        _assign(db, tenant, user, sales, primary=True)
        sales.active = False
        db.commit()
        ctx = build_effective_job_context(db, user)
        assert ctx.needs_job_role_assignment is True

    def test_set_active_job_role_persists(self, db):
        tenant, user = _user(db)
        sales = _role(db, tenant, "sales", "業務", ["sales_quote"])
        field = _role(db, tenant, "field", "現場", ["incident_handover"])
        _assign(db, tenant, user, sales, primary=True)
        _assign(db, tenant, user, field)
        set_active_job_role(db, user, field.id)
        db.commit()
        db.refresh(user)
        assert user.active_job_role_id == field.id

    def test_set_active_job_role_rejects_unassigned(self, db):
        tenant, user = _user(db)
        sales = _role(db, tenant, "sales", "業務", ["sales_quote"])
        with pytest.raises(ValueError):
            set_active_job_role(db, user, sales.id)


class TestModuleJobRoleAllowlist:
    def test_module_with_allowlist_requires_matching_job_role(self, db):
        tenant, user = _user(db)
        _module(db, "sales_quote", allowed_job_role_keys=["sales"])
        _bind(db, tenant, "sales_quote")
        sales = _role(db, tenant, "sales", "業務", ["sales_quote"])
        _assign(db, tenant, user, sales, primary=True)

        registry = ModuleRegistry(db)
        keys = [
            m["module_key"]
            for m in registry.get_available_modules(
                tenant_id=tenant.id, user_roles=["employee"],
                user_department_ids=[], job_role_keys=["sales"],
            )
        ]
        assert keys == ["sales_quote"]

        keys_no_role = [
            m["module_key"]
            for m in registry.get_available_modules(
                tenant_id=tenant.id, user_roles=["employee"],
                user_department_ids=[], job_role_keys=[],
            )
        ]
        assert keys_no_role == []

    def test_job_role_keys_none_skips_filter(self, db):
        tenant, _ = _user(db)
        _module(db, "sales_quote", allowed_job_role_keys=["sales"])
        _bind(db, tenant, "sales_quote")
        registry = ModuleRegistry(db)
        keys = [
            m["module_key"]
            for m in registry.get_available_modules(
                tenant_id=tenant.id, user_roles=["employee"],
                user_department_ids=[], job_role_keys=None,
            )
        ]
        assert keys == ["sales_quote"]


class TestModuleAccessGuards:
    def test_assert_module_access_denied_without_job_role(self, db):
        tenant, user = _user(db)
        _module(db, "sales_quote", allowed_job_role_keys=["sales"])
        _bind(db, tenant, "sales_quote")
        with pytest.raises(ModuleAccessDenied):
            assert_module_access(db, user, "sales_quote")

    def test_assert_module_access_allowed_with_job_role(self, db):
        tenant, user = _user(db)
        _module(db, "sales_quote", allowed_job_role_keys=["sales"])
        _bind(db, tenant, "sales_quote")
        sales = _role(db, tenant, "sales", "業務", ["sales_quote"])
        _assign(db, tenant, user, sales, primary=True)
        module = assert_module_access(db, user, "sales_quote")
        assert module["module_key"] == "sales_quote"

    def test_assert_module_access_unknown_module(self, db):
        tenant, user = _user(db)
        with pytest.raises(ModuleAccessDenied):
            assert_module_access(db, user, "nope")

    def test_assert_form_access_via_claiming_module(self, db):
        tenant, user = _user(db)
        m = _module(db, "sales_quote", allowed_job_role_keys=["sales"])
        m.form_definition_ids = ["quote"]
        db.commit()
        _bind(db, tenant, "sales_quote")

        # 無職能 → 擋下
        with pytest.raises(ModuleAccessDenied):
            assert_form_access(db, user, "quote")

        # 指派後放行
        sales = _role(db, tenant, "sales", "業務", ["sales_quote"])
        _assign(db, tenant, user, sales, primary=True)
        assert_form_access(db, user, "quote")

    def test_assert_form_access_unclaimed_form_open(self, db):
        tenant, user = _user(db)
        assert_form_access(db, user, "orphan_form")  # 無模組認領 → 開放


class TestTenantConfigMerge:
    def test_effective_config_merges_defaults_and_overrides(self, db):
        tenant, _ = _user(db)
        _bind(db, tenant, "sales_quote")
        registry = ModuleRegistry(db)
        result = registry.update_config_versioned(
            tenant.id, "sales_quote", {"tax_rate": 0, "default_payment_terms": "月結60天"}
        )
        assert result["config_version"] == 1
        assert result["effective"]["tax_rate"] == 0
        assert result["effective"]["default_payment_terms"] == "月結60天"
        # 未覆寫的鍵保留預設
        assert result["effective"]["require_approval"] is True
        assert result["effective"]["high_risk_fields"] == ["unit_price", "total", "tax"]

    def test_config_version_increments(self, db):
        tenant, _ = _user(db)
        _bind(db, tenant, "sales_quote")
        registry = ModuleRegistry(db)
        registry.update_config_versioned(tenant.id, "sales_quote", {"tax_rate": 5})
        result = registry.update_config_versioned(tenant.id, "sales_quote", {"tax_rate": 6})
        assert result["config_version"] == 2

    def test_config_validation_rejects_unknown_key(self, db):
        tenant, _ = _user(db)
        _bind(db, tenant, "sales_quote")
        registry = ModuleRegistry(db)
        with pytest.raises(ValueError, match="未知設定鍵"):
            registry.update_config_versioned(
                tenant.id, "sales_quote", {"not_a_key": 1}
            )

    def test_config_validation_rejects_wrong_type(self, db):
        tenant, _ = _user(db)
        _bind(db, tenant, "sales_quote")
        registry = ModuleRegistry(db)
        with pytest.raises(ValueError, match="應為"):
            registry.update_config_versioned(
                tenant.id, "sales_quote", {"tax_rate": "五"}
            )

    def test_effective_config_without_binding(self, db):
        tenant, _ = _user(db)
        registry = ModuleRegistry(db)
        result = registry.get_effective_config(tenant.id, "sales_quote")
        assert result["enabled"] is False
        assert result["config_version"] == 0
        assert result["effective"]["require_approval"] is True
