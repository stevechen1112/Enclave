"""Architecture contracts for non-database tenant boundaries in Phase P2."""

from __future__ import annotations

import inspect


def test_background_cross_tenant_purge_uses_only_maintenance_identity() -> None:
    from app.tasks.input_capture_tasks import purge_mka_retention

    source = inspect.getsource(purge_mka_retention.run)
    assert "MaintenanceSessionLocal()" in source
    assert "apply_rls_bypass(" in source
    assert 'actor_identity="celery:purge_mka_retention"' in source
    assert "db = SessionLocal()" not in source


def test_redis_retrieval_keys_bind_tenant_policy_and_scope() -> None:
    from app.services.kb_retrieval import KnowledgeBaseRetriever

    source = inspect.getsource(KnowledgeBaseRetriever._cache_key)
    assert "tenant_id" in source
    assert "policy_fingerprint" in source
    assert "filter_dict" in source


def test_object_storage_and_export_download_enforce_tenant_prefix() -> None:
    from app.api.v1.endpoints.forms import download_form_export
    from app.services.storage import assert_key_matches_tenant

    guard_source = inspect.getsource(assert_key_matches_tenant)
    export_source = inspect.getsource(download_form_export)
    assert 'startswith(f"{tenant_id}/")' in guard_source
    assert "assert_key_matches_tenant" in export_source
    assert "current_user.tenant_id" in export_source


def test_review_routes_bind_rows_to_authenticated_tenant() -> None:
    from app.services import review_workspace

    source = inspect.getsource(review_workspace.list_review_items)
    assert "current_user.tenant_id" in source
    assert "DerivedArtifact.tenant_id == tenant_id" in source
    assert "LegacyReviewItem.tenant_id == tenant_id" in source


def test_signed_media_routes_scope_before_generating_object_response() -> None:
    from app.api.v1.endpoints.video_assets import (
        _asset_or_404,
        get_video_artifact_content,
        get_video_content,
    )

    asset_source = inspect.getsource(_asset_or_404)
    video_source = inspect.getsource(get_video_content)
    artifact_source = inspect.getsource(get_video_artifact_content)
    assert "SourceAsset.tenant_id == tenant_id" in asset_source
    assert "SourceAsset.tombstoned_at.is_(None)" in asset_source
    assert video_source.index("apply_rls_context") < video_source.index("_asset_or_404")
    assert "DerivedArtifact.tenant_id == tenant_id" in artifact_source
    assert "asset_access_allows" in artifact_source


def test_pack_and_realtime_routes_derive_tenant_from_authenticated_user() -> None:
    from app.packs.sales_quote.endpoints.realtime_voice import _own_quote_run
    from app.packs.mka import api as mka_api

    pack_source = inspect.getsource(mka_api)
    realtime_source = inspect.getsource(_own_quote_run)
    assert "PackTenantContext(tenant_id=current_user.tenant_id" in pack_source
    assert "TaskRun.tenant_id == user.tenant_id" in realtime_source
    assert "TaskRun.user_id == user.id" in realtime_source
