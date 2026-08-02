"""Deny-first revoke / tombstone / cache epoch / ACL alignment tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.authorization import AuthorizationContext
from app.gateway.service_auth import mint_service_token, verify_service_token
from app.models.tenant import Tenant
from app.models.user import User
from app.models.document import Document
from app.models.permission import Department
from app.db.base_class import Base


@pytest.fixture
def db_session(test_engine):
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    db = Session()
    yield db
    db.close()


def test_service_token_roundtrip():
    token = mint_service_token(audience="sidecar", ttl_seconds=60)
    assert verify_service_token(token, "sidecar")
    assert not verify_service_token(token, "other")


def test_forged_token_rejected():
    assert not verify_service_token("v1.sidecar.x.9999999999.deadbeef", "sidecar")


def test_document_list_acl_matches_authz_ancestors(db_session):
    tenant = Tenant(id=uuid.uuid4(), name="ACLTenant", plan="free", status="active")
    db_session.add(tenant)
    parent = Department(id=uuid.uuid4(), tenant_id=tenant.id, name="HQ", parent_id=None)
    child = Department(id=uuid.uuid4(), tenant_id=tenant.id, name="QA", parent_id=parent.id)
    db_session.add_all([parent, child])
    db_session.flush()
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"qa-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="employee",
        department_id=child.id,
        is_superuser=False,
    )
    user.department = child
    child.parent = parent
    parent.parent = None
    db_session.add(user)
    db_session.flush()

    other_dept = Department(id=uuid.uuid4(), tenant_id=tenant.id, name="Secret", parent_id=None)
    db_session.add(other_dept)
    db_session.flush()

    doc_parent = Document(
        id=uuid.uuid4(), tenant_id=tenant.id, filename="hq.txt",
        file_path="/tmp/hq.txt", file_type="txt", file_size=1,
        status="ready", uploaded_by=user.id, department_id=parent.id,
    )
    doc_other = Document(
        id=uuid.uuid4(), tenant_id=tenant.id, filename="secret.txt",
        file_path="/tmp/secret.txt", file_type="txt", file_size=1,
        status="ready", uploaded_by=user.id, department_id=other_dept.id,
    )
    db_session.add_all([doc_parent, doc_other])
    db_session.commit()

    authz = AuthorizationContext.from_user(user)
    assert parent.id in authz.department_ids
    assert authz.can_access_document(tenant.id, parent.id)
    assert not authz.can_access_document(tenant.id, doc_other.department_id)

    # admin/hr 不再自動 bypass
    admin = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"adm-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="admin",
        department_id=child.id,
        is_superuser=False,
    )
    admin.department = child
    db_session.add(admin)
    db_session.commit()
    admin_authz = AuthorizationContext.from_user(admin)
    assert not admin_authz.has_kb_admin
    assert not admin_authz.can_access_document(tenant.id, other_dept.id)

    from app.api.deps_permissions import can_access_document_by_department
    assert can_access_document_by_department(user, parent.id)
    assert not can_access_document_by_department(user, other_dept.id)
    assert not can_access_document_by_department(admin, other_dept.id)


def test_tombstone_deny_first(db_session):
    tenant = Tenant(id=uuid.uuid4(), name="Tomb", plan="free", status="active")
    db_session.add(tenant)
    db_session.flush()
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"tomb-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="admin",
        is_superuser=False,
    )
    db_session.add(user)
    db_session.flush()
    doc = Document(
        id=uuid.uuid4(), tenant_id=tenant.id, filename="gone.txt",
        file_path="/tmp/gone.txt", file_type="txt", file_size=1,
        status="ready", uploaded_by=user.id,
    )
    db_session.add(doc)
    db_session.commit()
    doc.tombstoned_at = datetime.now(timezone.utc)
    db_session.commit()

    authz = AuthorizationContext(
        tenant_id=tenant.id, subject_id=user.id, is_superuser=True,
    )
    live = (
        db_session.query(Document)
        .filter(Document.tenant_id == tenant.id, Document.tombstoned_at.is_(None))
        .count()
    )
    assert live == 0
    assert authz.tenant_id == tenant.id


def test_source_acl_fail_closed_without_principal():
    from app.gateway.authorization import GatewayAuthorizer

    authz = AuthorizationContext(
        tenant_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        role_ids=["employee"],
        is_superuser=False,
    )
    authorizer = GatewayAuthorizer()
    assert authorizer._check_source_acl(authz, ["nas_smb"]) is False


def test_pipeshub_mock_requires_explicit_flag():
    import asyncio
    from app.gateway.adapters.pipeshub_http import PipesHubHTTPAdapter

    adapter = PipesHubHTTPAdapter(base_url="http://127.0.0.1:9", api_key="")

    async def _run():
        # 無 allow_mock → 必須 error，不可假 completed
        r = await adapter.sync_connector(
            "sharepoint",
            {"mock_resources": [{"source_record_id": "x"}]},
        )
        assert r.get("status") == "error"
        # 明確 allow_mock → 可 completed + mode=mock
        r2 = await adapter.sync_connector(
            "sharepoint",
            {"mock_resources": [{"source_record_id": "x"}], "allow_mock": True},
        )
        assert r2.get("status") == "completed"
        assert r2.get("mode") in ("mock", "mock_after_error")

    asyncio.run(_run())
