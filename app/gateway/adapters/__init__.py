"""
Production Gateway Adapter exports.

Stub / mock adapters are NOT re-exported here (DD P1).
Tests may import them from their concrete modules:
  - app.gateway.adapters.base.MockAdapter
  - app.gateway.adapters.ragflow.RAGFlowAdapter (fail-closed stub)
"""
from app.gateway.adapters.base import BaseAdapter
from app.gateway.adapters.enclave import EnclaveCanonicalAdapter
from app.gateway.adapters.ragflow_http import RAGFlowHTTPAdapter
from app.gateway.adapters.pipeshub_http import PipesHubHTTPAdapter
from app.gateway.adapters.weknora_http import WeKnoraHTTPAdapter

__all__ = [
    "BaseAdapter",
    "EnclaveCanonicalAdapter",
    "RAGFlowHTTPAdapter",
    "PipesHubHTTPAdapter",
    "WeKnoraHTTPAdapter",
]
