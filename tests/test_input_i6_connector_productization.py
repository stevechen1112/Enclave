"""Input I6 connector, ACL, canonical asset and batch acceptance tests."""

from __future__ import annotations

import hashlib
import uuid


def test_nas_snapshot_is_deterministic_and_never_complete_when_truncated(tmp_path):
    from app.services.nas_local_connector import scan_local_nas

    for index in range(12):
        path = tmp_path / "line-a" / f"manual-{index:02d}.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"manual {index}", encoding="utf-8")
    partial = scan_local_nas(str(tmp_path), max_files=10)
    full = scan_local_nas(str(tmp_path), max_files=20)
    replay = scan_local_nas(str(tmp_path), max_files=20)

    assert partial["snapshot_complete"] is False
    assert partial["total_eligible"] == 12
    assert full["snapshot_complete"] is True
    assert full["snapshot_id"] == replay["snapshot_id"]
    assert full["cursor"] == replay["cursor"]
    assert all(item["metadata"]["path"].startswith("line-a/") for item in full["resources"])


def test_connector_sdk_rate_limit_and_token_refresh_are_bounded():
    from app.platform.connectors import (
        ConnectorAuthExpired,
        ConnectorRateLimited,
        retry_connector_call,
    )

    calls = 0
    refreshed = 0
    sleeps: list[float] = []

    def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectorAuthExpired("expired")
        if calls == 2:
            raise ConnectorRateLimited(500)
        return "ok"

    def refresh():
        nonlocal refreshed
        refreshed += 1

    assert retry_connector_call(
        operation,
        attempts=3,
        max_wait_seconds=2,
        sleep=sleeps.append,
        refresh_credentials=refresh,
    ) == "ok"
    assert calls == 3
    assert refreshed == 1
    assert sleeps == [2]


def test_complete_acl_snapshot_revokes_permission_drift(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.connector import SourceAclEntry
    from app.models.tenant import Tenant
    from app.services.external_principal import ExternalPrincipalService
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="I6 ACL", plan="free", status="active")
        db.add(tenant)
        db.flush()
        service = ExternalPrincipalService()
        initial = [
            {
                "provider": "nas_smb",
                "principal_external_id": principal,
                "source_record_id": "nas:manual.txt",
                "permission": "read",
            }
            for principal in ("worker-a", "worker-b")
        ]
        service.replace_acl_snapshot(
            db, tenant.id, initial, source_record_ids={"nas:manual.txt"}
        )
        result = service.replace_acl_snapshot(
            db, tenant.id, initial[:1], source_record_ids={"nas:manual.txt"}
        )
        assert result["revoked"] == 1
        assert db.query(SourceAclEntry).filter(
            SourceAclEntry.tenant_id == tenant.id,
            SourceAclEntry.source_record_id == "nas:manual.txt",
        ).count() == 1
    finally:
        db.close()


def test_connector_asset_is_canonical_first_and_replay_safe(tmp_path, test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.asset import AssetRevision, SourceAsset
    from app.models.tenant import Tenant
    from app.services.connector_asset import materialize_connector_asset
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="I6 Asset", plan="free", status="active")
        db.add(tenant)
        db.flush()
        path = tmp_path / "sop.txt"
        path.write_text("revision one", encoding="utf-8")
        first_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        resource = {
            "source_record_id": "nas:plant/sop.txt",
            "title": "sop.txt",
            "content_hash": first_hash,
            "mime_type": "text/plain",
            "metadata": {"folder": "plant"},
        }
        asset, rev1 = materialize_connector_asset(
            db,
            tenant_id=tenant.id,
            source_system="nas_smb",
            resource=resource,
            content_uri=str(path),
            byte_size=path.stat().st_size,
            created_by=None,
        )
        replay_asset, replay_rev = materialize_connector_asset(
            db,
            tenant_id=tenant.id,
            source_system="nas_smb",
            resource=resource,
            content_uri=str(path),
            byte_size=path.stat().st_size,
            created_by=None,
        )
        assert replay_asset.id == asset.id
        assert replay_rev.id == rev1.id

        path.write_text("revision two", encoding="utf-8")
        resource["content_hash"] = hashlib.sha256(path.read_bytes()).hexdigest()
        _, rev2 = materialize_connector_asset(
            db,
            tenant_id=tenant.id,
            source_system="nas_smb",
            resource=resource,
            content_uri=str(path),
            byte_size=path.stat().st_size,
            created_by=None,
        )
        assert rev2.revision == 2
        assert rev2.supersedes_revision_id == rev1.id
        assert db.query(SourceAsset).filter(SourceAsset.tenant_id == tenant.id).count() == 1
        assert db.query(AssetRevision).filter(AssetRevision.tenant_id == tenant.id).count() == 2
    finally:
        db.close()


def test_batch_manifest_retries_failed_items_only(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.connector import ImportBatchItem
    from app.models.tenant import Tenant
    from app.services.connector_batch import ConnectorBatchService
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="I6 Batch", plan="free", status="active")
        db.add(tenant)
        db.flush()
        resources = [
            {"source_record_id": "nas:a.txt", "content_hash": "a" * 64},
            {"source_record_id": "nas:b.txt", "content_hash": "b" * 64},
        ]
        service = ConnectorBatchService()
        batch = service.create(
            db,
            tenant_id=tenant.id,
            connector_instance_id=None,
            resources=resources,
        )
        service.mark(
            db,
            tenant_id=tenant.id,
            batch_id=batch.id,
            source_record_id="nas:a.txt",
            succeeded=True,
        )
        service.mark(
            db,
            tenant_id=tenant.id,
            batch_id=batch.id,
            source_record_id="nas:b.txt",
            succeeded=False,
            error_code="temporary_provider_error",
        )
        assert batch.status == "partial"
        assert service.failed_resources(
            db, tenant_id=tenant.id, batch_id=batch.id
        ) == [resources[1]]
        assert db.query(ImportBatchItem).filter(
            ImportBatchItem.status == "succeeded"
        ).count() == 1
    finally:
        db.close()
