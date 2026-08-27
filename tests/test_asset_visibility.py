from __future__ import annotations

from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.authorization import AuthorizationContext
from app.models.asset import SourceAsset
from app.models.connector import ExternalPrincipal, SourceAclEntry
from app.models.mka import JobRole
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.platform.assets import AssetAccessPolicy
from app.services.asset_visibility import asset_access_allows, canonical_asset_acl


def _session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    for table in (
        Tenant.__table__,
        Department.__table__,
        JobRole.__table__,
        User.__table__,
        SourceAsset.__table__,
        ExternalPrincipal.__table__,
        SourceAclEntry.__table__,
    ):
        table.create(engine, checkfirst=True)
    return engine, sessionmaker(bind=engine)()


def _tenant_user(db, *, role="employee", department=None):
    tenant = Tenant(name=f"tenant-{uuid4().hex[:6]}")
    db.add(tenant)
    db.flush()
    user = User(
        tenant_id=tenant.id,
        department_id=department.id if department else None,
        email=f"{uuid4().hex}@example.invalid",
        hashed_password="x",
        role=role,
        status="active",
    )
    db.add(user)
    db.flush()
    return tenant, user


def test_policy_is_deny_first_and_preserves_legacy_visibility():
    tenant_id = uuid4()
    owner_id = uuid4()
    department_id = uuid4()
    outsider = AuthorizationContext(
        tenant_id=tenant_id,
        subject_id=uuid4(),
        role_ids=("employee",),
    )
    owner = AuthorizationContext(
        tenant_id=tenant_id,
        subject_id=owner_id,
        role_ids=("employee",),
    )

    assert AssetAccessPolicy.from_mapping({"uploaded_by": str(owner_id)}).allows(
        outsider
    )
    assert AssetAccessPolicy.from_mapping(
        {"visibility": "private", "uploaded_by": str(owner_id)}
    ).allows(owner)
    assert not AssetAccessPolicy.from_mapping(
        {"visibility": "private", "uploaded_by": str(owner_id)}
    ).allows(outsider)

    department_user = AuthorizationContext(
        tenant_id=tenant_id,
        subject_id=uuid4(),
        role_ids=("employee",),
        department_ids=(department_id,),
    )
    legacy_department = AssetAccessPolicy.from_mapping(
        {"department_id": str(department_id)}
    )
    assert legacy_department.visibility == "restricted"
    assert legacy_department.allows(department_user)
    assert not legacy_department.allows(outsider)

    denied = AssetAccessPolicy.from_mapping(
        {
            "visibility": "tenant",
            "denied_subject_ids": [str(owner_id)],
            "owner_subject_id": str(owner_id),
        }
    )
    assert not denied.allows(owner)


def test_asset_visibility_checks_tenant_lifecycle_and_malformed_policy():
    engine, db = _session()
    try:
        tenant, user = _tenant_user(db)
        authz = AuthorizationContext.from_user(user)
        asset = SourceAsset(
            tenant_id=tenant.id,
            asset_kind="video",
            title="Visible",
            source_system="upload",
            acl_reference=canonical_asset_acl(owner_subject_id=user.id),
            current_revision=1,
            status="active",
            created_by=user.id,
        )
        db.add(asset)
        db.flush()
        assert asset_access_allows(db, asset, authz=authz)

        other_tenant, other_user = _tenant_user(db)
        assert not asset_access_allows(
            db, asset, authz=AuthorizationContext.from_user(other_user)
        )
        assert other_tenant.id != tenant.id

        asset.acl_reference = {"allowed_role_ids": "employee"}
        assert not asset_access_allows(db, asset, authz=authz)
        asset.acl_reference = canonical_asset_acl(owner_subject_id=user.id)
        asset.tombstoned_at = user.created_at
        assert not asset_access_allows(db, asset, authz=authz)
    finally:
        db.close()
        engine.dispose()


def test_connector_acl_requires_allow_and_deny_wins():
    engine, db = _session()
    try:
        tenant, user = _tenant_user(db)
        authz = AuthorizationContext.from_user(user)
        asset = SourceAsset(
            tenant_id=tenant.id,
            asset_kind="document",
            title="NAS SOP",
            source_system="nas_smb",
            source_record_id="nas://sop/1",
            acl_reference=canonical_asset_acl(owner_subject_id=user.id),
            current_revision=1,
            status="active",
            created_by=user.id,
        )
        principal = ExternalPrincipal(
            tenant_id=tenant.id,
            provider="nas_smb",
            external_id="operator-1",
            principal_type="user",
            mapped_subject_id=user.id,
            mapped_subject_type="user",
        )
        db.add_all([asset, principal])
        db.flush()
        assert not asset_access_allows(db, asset, authz=authz)

        db.add(
            SourceAclEntry(
                tenant_id=tenant.id,
                source_record_id=asset.source_record_id,
                principal_id=principal.id,
                permission="read",
                effect="allow",
            )
        )
        db.flush()
        assert asset_access_allows(db, asset, authz=authz)

        db.add(
            SourceAclEntry(
                tenant_id=tenant.id,
                source_record_id=asset.source_record_id,
                principal_id=principal.id,
                permission="read",
                effect="deny",
            )
        )
        db.flush()
        assert not asset_access_allows(db, asset, authz=authz)
    finally:
        db.close()
        engine.dispose()
