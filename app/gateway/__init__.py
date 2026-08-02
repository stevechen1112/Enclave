"""
Phase 1 — Gateway Module
"""
from app.gateway.contracts import (
    GatewayRequest, GatewayResponse, SearchRequest, SearchDomain,
    ChunkResult, Citation, IngestRequest, DeleteRequest,
    GatewayError, AuditTrail,
)
from app.gateway.authorization import GatewayAuthorizer, PolicyDecision
from app.gateway.router import GatewayRouter
from app.gateway.adapters.base import BaseAdapter, MockAdapter
from app.gateway.resilience import CircuitBreaker, RetryConfig, with_retry, CircuitOpenError

__all__ = [
    "GatewayRequest", "GatewayResponse", "SearchRequest", "SearchDomain",
    "ChunkResult", "Citation", "IngestRequest", "DeleteRequest",
    "GatewayError", "AuditTrail",
    "GatewayAuthorizer", "PolicyDecision",
    "GatewayRouter",
    "BaseAdapter", "MockAdapter",
    "CircuitBreaker", "RetryConfig", "with_retry", "CircuitOpenError",
]
