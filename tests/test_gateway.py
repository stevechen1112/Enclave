"""
Phase 1 — Gateway Contract Tests

測試 Gateway 核心功能：
  - Adapter 契約（MockAdapter 實作所有 BaseAdapter 方法）
  - Router 路由與聚合
  - Authorizer 授權決策
  - Resilience（Circuit Breaker + Retry）
"""
import asyncio
import uuid
import pytest
from app.core.authorization import AuthorizationContext
from app.gateway.contracts import SearchDomain, ChunkResult
from app.gateway.router import GatewayRouter
from app.gateway.authorization import GatewayAuthorizer
from app.gateway.adapters.base import MockAdapter, BaseAdapter
from app.gateway.resilience import CircuitBreaker, RetryConfig, with_retry, CircuitOpenError


# ── Helpers ──

def _make_authz(role="employee", is_superuser=False):
    """建立測試用 AuthorizationContext。"""
    return AuthorizationContext(
        tenant_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        role_ids=[role],
        is_superuser=is_superuser,
        policy_revision=1,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Adapter Contract Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestMockAdapter:
    """MockAdapter 實作所有 BaseAdapter 契約。"""

    @pytest.mark.asyncio
    async def test_capabilities(self):
        adapter = MockAdapter(domain="document")
        caps = await adapter.capabilities()
        assert caps["provider"] == "mock"
        assert "search" in caps["features"]

    @pytest.mark.asyncio
    async def test_health(self):
        adapter = MockAdapter()
        health = await adapter.health()
        assert health["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_unhealthy(self):
        adapter = MockAdapter()
        adapter.set_unhealthy()
        health = await adapter.health()
        assert health["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_search_empty(self):
        adapter = MockAdapter()
        authz = _make_authz()
        results = await adapter.search(authz, "test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_after_ingest(self):
        adapter = MockAdapter()
        authz = _make_authz()
        doc_id = uuid.uuid4()

        await adapter.ingest(doc_id, 1, "file://test.pdf", "abc123", "pdf", authz)
        results = await adapter.search(authz, "test query")
        assert len(results) > 0
        assert results[0].document_id == str(doc_id)

    @pytest.mark.asyncio
    async def test_search_excludes_deleted(self):
        adapter = MockAdapter()
        authz = _make_authz()
        doc_id = uuid.uuid4()

        await adapter.ingest(doc_id, 1, "file://test.pdf", "abc123", "pdf", authz)
        await adapter.delete("document", str(doc_id), 2, "idem-1")
        results = await adapter.search(authz, "test query")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_ingest_idempotent(self):
        adapter = MockAdapter()
        authz = _make_authz()
        doc_id = uuid.uuid4()

        r1 = await adapter.ingest(doc_id, 1, "file://test.pdf", "abc", "pdf", authz)
        r2 = await adapter.ingest(doc_id, 2, "file://test.pdf", "def", "pdf", authz)
        assert r1["document_id"] == r2["document_id"]
        assert adapter._ingested[str(doc_id)]["revision"] == 2

    @pytest.mark.asyncio
    async def test_reconcile_converged(self):
        adapter = MockAdapter()
        authz = _make_authz()
        doc_id = uuid.uuid4()

        await adapter.ingest(doc_id, 3, "file://test.pdf", "abc", "pdf", authz)
        result = await adapter.reconcile("document", str(doc_id), 3)
        assert result["converged"] is True

    @pytest.mark.asyncio
    async def test_reconcile_diverged(self):
        adapter = MockAdapter()
        authz = _make_authz()
        doc_id = uuid.uuid4()

        await adapter.ingest(doc_id, 1, "file://test.pdf", "abc", "pdf", authz)
        result = await adapter.reconcile("document", str(doc_id), 5)
        assert result["converged"] is False


# ═══════════════════════════════════════════════════════════════════════════════
#  Authorizer Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGatewayAuthorizer:
    """GatewayAuthorizer 授權決策。"""

    def test_authorize_search_allowed(self):
        authorizer = GatewayAuthorizer()
        authz = _make_authz(role="employee")
        decision = authorizer.authorize_search(authz)
        assert decision.allowed is True

    def test_authorize_ingest_admin_allowed(self):
        authorizer = GatewayAuthorizer()
        authz = _make_authz(role="admin")
        decision = authorizer.authorize_ingest(authz, uuid.uuid4())
        assert decision.allowed is True

    def test_authorize_ingest_employee_denied(self):
        authorizer = GatewayAuthorizer()
        authz = _make_authz(role="employee")
        decision = authorizer.authorize_ingest(authz, uuid.uuid4())
        assert decision.allowed is False

    def test_authorize_ingest_superuser_allowed(self):
        authorizer = GatewayAuthorizer()
        authz = _make_authz(role="viewer", is_superuser=True)
        decision = authorizer.authorize_ingest(authz, uuid.uuid4())
        assert decision.allowed is True

    def test_deny_set(self):
        authorizer = GatewayAuthorizer()
        resource_id = "doc-123"
        subject_id = uuid.uuid4()

        assert authorizer.is_denied(resource_id, subject_id) is False
        authorizer.add_deny_entry(resource_id, subject_id)
        assert authorizer.is_denied(resource_id, subject_id) is True
        authorizer.remove_deny_entry(resource_id, subject_id)
        assert authorizer.is_denied(resource_id, subject_id) is False


# ═══════════════════════════════════════════════════════════════════════════════
#  Router Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGatewayRouter:
    """GatewayRouter 路由與聚合。"""

    @pytest.mark.asyncio
    async def test_search_single_adapter(self):
        router = GatewayRouter()
        mock = MockAdapter(domain="document")
        router.register_adapter("document", mock)

        authz = _make_authz()
        doc_id = uuid.uuid4()
        await mock.ingest(doc_id, 1, "file://test.pdf", "abc", "pdf", authz)

        response = await router.search(
            authz=authz,
            query="test",
            domain=SearchDomain.DOCUMENT,
        )
        assert response.status == "success"
        assert len(response.results) > 0

    @pytest.mark.asyncio
    async def test_search_unauthorized(self):
        router = GatewayRouter()
        mock = MockAdapter()
        router.register_adapter("document", mock)

        # 使用無 tenant 的 authz（應被拒絕）
        authz = AuthorizationContext(
            tenant_id=None,  # type: ignore
            subject_id=uuid.uuid4(),
            policy_revision=1,
        )
        response = await router.search(authz=authz, query="test")
        assert response.status == "error"

    @pytest.mark.asyncio
    async def test_search_no_adapter(self):
        router = GatewayRouter()
        authz = _make_authz()
        response = await router.search(authz=authz, query="test")
        assert response.status == "partial"
        assert len(response.errors) > 0

    @pytest.mark.asyncio
    async def test_search_hybrid_multi_adapter(self):
        router = GatewayRouter()
        doc_mock = MockAdapter(domain="document")
        wiki_mock = MockAdapter(domain="wiki")
        router.register_adapter("document", doc_mock)
        router.register_adapter("wiki", wiki_mock)

        authz = _make_authz()
        doc_id = uuid.uuid4()
        await doc_mock.ingest(doc_id, 1, "file://test.pdf", "abc", "pdf", authz)
        await wiki_mock.ingest(uuid.uuid4(), 1, "file://wiki.pdf", "def", "pdf", authz)

        response = await router.search(
            authz=authz,
            query="test",
            domain=SearchDomain.HYBRID,
        )
        assert response.status == "success"
        # 兩個 adapter 都有結果
        assert len(response.audit_trail.providers_called) == 2


# ═══════════════════════════════════════════════════════════════════════════════
#  Resilience Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCircuitBreaker:
    """Circuit Breaker 狀態轉換。"""

    @pytest.mark.asyncio
    async def test_closed_to_open(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout=60)

        # 兩次失敗 → OPEN
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb._call_async(
                    lambda: _raise_async(ValueError("fail")),
                    timeout=5.0,
                )
        assert cb.state.value == "open"

    @pytest.mark.asyncio
    async def test_open_blocks_requests(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=60)

        with pytest.raises(ValueError):
            await cb._call_async(
                lambda: _raise_async(ValueError("fail")),
                timeout=5.0,
            )

        with pytest.raises(CircuitOpenError):
            await cb._call_async(
                lambda: _return_async("ok"),
                timeout=5.0,
            )

    @pytest.mark.asyncio
    async def test_half_open_to_closed(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.01)

        # 觸發 OPEN
        with pytest.raises(ValueError):
            await cb._call_async(
                lambda: _raise_async(ValueError("fail")),
                timeout=5.0,
            )

        # 等待 recovery_timeout
        await asyncio.sleep(0.02)

        # 成功 → CLOSED
        result = await cb._call_async(
            lambda: _return_async("ok"),
            timeout=5.0,
        )
        assert result == "ok"
        assert cb.state.value == "closed"

    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.01)

        with pytest.raises(ValueError):
            await cb._call_async(
                lambda: _raise_async(ValueError("fail")),
                timeout=5.0,
            )

        await asyncio.sleep(0.02)

        # 探測失敗 → 回到 OPEN
        with pytest.raises(ValueError):
            await cb._call_async(
                lambda: _raise_async(ValueError("fail again")),
                timeout=5.0,
            )
        assert cb.state.value == "open"


class TestRetry:
    """Retry 機制。"""

    @pytest.mark.asyncio
    async def test_retry_success_after_failures(self):
        call_count = [0]

        async def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise asyncio.TimeoutError("timeout")
            return "ok"

        config = RetryConfig(max_retries=3, base_delay=0.01)
        result = await with_retry(flaky, config)
        assert result == "ok"
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        async def always_fails():
            raise asyncio.TimeoutError("timeout")

        config = RetryConfig(max_retries=2, base_delay=0.01)
        with pytest.raises(asyncio.TimeoutError):
            await with_retry(always_fails, config)

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        async def raises_value_error():
            raise ValueError("not retryable")

        config = RetryConfig(max_retries=3, base_delay=0.01)
        with pytest.raises(ValueError):
            await with_retry(raises_value_error, config)


# ── Async helpers ──

async def _raise_async(exc: Exception):
    raise exc


async def _return_async(value):
    return value
