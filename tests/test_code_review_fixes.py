"""Regressions for code-review P1–P3 fixes."""
from __future__ import annotations

import inspect
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


class TestResourceWideDeny:
    def test_is_denied_honors_resource_wide_sentinel(self):
        from app.services.policy_deny import RESOURCE_WIDE_DENY_SUBJECT, is_denied
        from app.models.policy_deny import PolicyDenyEntry

        db = MagicMock()
        row = MagicMock()
        row.expires_at = None
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = row
        db.query.return_value = q

        assert is_denied(db, "document", "doc-1", uuid.uuid4()) is True
        # filter used resource_id path
        db.query.assert_called_with(PolicyDenyEntry)
        assert RESOURCE_WIDE_DENY_SUBJECT == uuid.UUID(int=0)

    def test_authorizer_memory_resource_deny_blocks_other_subject(self):
        from app.gateway.authorization import GatewayAuthorizer
        from app.services.policy_deny import RESOURCE_WIDE_DENY_SUBJECT

        auth = GatewayAuthorizer()
        doc = str(uuid.uuid4())
        auth._deny_cache[doc] = {RESOURCE_WIDE_DENY_SUBJECT}
        other = uuid.uuid4()
        with patch("app.services.policy_deny.is_denied", return_value=False):
            # bypass DB by making SessionLocal fail → would fail-closed; instead
            # ensure memory path hits first
            assert auth.is_denied(doc, other) is True

    def test_revocation_calls_deny_resource(self):
        from app.services import document_revocation as dr

        src = inspect.getsource(dr.DocumentRevocationService.revoke)
        assert "deny_resource" in src
        assert "add_deny_entry" not in src


class TestWatcherReviewPreservesRevisionHistory:
    def test_watcher_hides_live_document_without_deleting_historical_chunks(self):
        from app.tasks import document_tasks as dt

        src = inspect.getsource(dt.watcher_ingest_file_task.run)
        assert "pending_review" in src
        assert "awaiting_review" in src
        assert "stale_index_cleared" in src
        assert "DocumentChunk).filter" not in src
        assert "existing.version = int(existing.version or 1) + 1" in src
        enqueue_idx = src.find(".enqueue(")
        status_idx = src.find('existing.status = "pending_review"')
        assert status_idx != -1 and enqueue_idx != -1 and status_idx < enqueue_idx


class TestSsoCallbackTenantFilter:
    def test_callback_filters_tenant_and_provider(self):
        from app.api.v1.endpoints import sso as sso_mod

        # CG-AUTH-SSO 重構後：過濾邏輯在 _get_cfg（tenant+provider+enabled），
        # callback 必須呼叫它並比對 state 的 tenant/provider
        src = inspect.getsource(sso_mod)
        assert "_get_cfg" in src
        assert "TenantSSOConfig.tenant_id ==" in src
        assert "TenantSSOConfig.provider ==" in src
        assert "TenantSSOConfig.enabled.is_(True)" in src
        cb_src = inspect.getsource(sso_mod.sso_callback)
        assert "State tenant mismatch" in cb_src
        assert "State provider mismatch" in cb_src
        assert "does not belong to this tenant" in cb_src


class TestDeployStopBeforeMigrate:
    def test_prod_and_staging_stop_then_migrate_then_up(self):
        for name in ("deploy-production.yml", "deploy-staging.yml"):
            text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            stop_idx = text.find("stop web worker worker-beat")
            mig_idx = text.find("run --rm -T migrate")
            provision_idx = text.find("run --rm -T provision-db-roles")
            up_idx = text.find("up -d --no-build --remove-orphans")
            assert all(
                index != -1 for index in (stop_idx, mig_idx, provision_idx, up_idx)
            ), name
            assert stop_idx < mig_idx < provision_idx < up_idx, name


class TestCredentialVaultEncryption:
    def test_roundtrip_seal_open(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-vault-32chars!!")
        from app.services import credential_vault as cv

        monkeypatch.setattr(cv, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(cv, "_DEFAULT_DIR", tmp_path / "var" / "credentials")
        path = cv.ensure_credential_dir() / "x.bin"
        payload = {"access_token": "tok", "refresh_token": "ref"}
        cv.write_credential_file(path, payload)
        raw = path.read_bytes()
        assert b"access_token" not in raw
        assert cv.read_credential_file(path)["access_token"] == "tok"

    def test_legacy_plaintext_json_still_readable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-vault-32chars!!")
        from app.services import credential_vault as cv

        monkeypatch.setattr(cv, "_REPO_ROOT", tmp_path)
        p = tmp_path / "legacy.json"
        p.write_text('{"access_token":"plain"}', encoding="utf-8")
        assert cv.read_credential_file(p)["access_token"] == "plain"


class TestGatewayRuntimeNoEmptyAuthorizer:
    def test_runtime_raises_when_authorizer_unavailable(self):
        from app.gateway import runtime as rt

        src = inspect.getsource(rt.get_configured_gateway_router)
        assert "GatewayAuthorizer()" not in src or "refusing empty deny cache" in src
        assert "refusing empty deny cache" in src
