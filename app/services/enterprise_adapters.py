"""ERP / CRM / MES adapter contracts — read-only → prefill → approved low-risk write."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EnterpriseAdapter(ABC):
    system: str = ""

    @abstractmethod
    def health(self) -> Dict[str, Any]:
        ...

    @abstractmethod
    def read(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    def prefill(self, form_key: str, context: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    def write(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        ...


class StubERPAdapter(EnterpriseAdapter):
    """Fail-closed stub until customer credentials/spec are provided (external gate)."""
    system = "erp"

    def __init__(self, configured: bool = False):
        self.configured = configured

    def health(self) -> Dict[str, Any]:
        return {
            "system": self.system,
            "configured": self.configured,
            "mode": "stub" if not self.configured else "live",
            "capabilities": ["read", "prefill", "low_risk_write"],
        }

    def read(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.configured:
            return {"status": "unavailable", "reason": "erp_credentials_missing", "items": []}
        return {"status": "ok", "items": []}

    def prefill(self, form_key: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if not self.configured:
            return {"status": "unavailable", "values": {}, "reason": "erp_credentials_missing"}
        return {"status": "ok", "values": {}}

    def write(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.configured:
            raise RuntimeError("erp adapter not configured — fail closed")
        return {"status": "ok", "operation": operation, "echo": payload}


class StubCRMAdapter(StubERPAdapter):
    system = "crm"


class StubMESAdapter(StubERPAdapter):
    system = "mes"


def get_adapter(system: str, configured: bool = False) -> EnterpriseAdapter:
    mapping = {
        "erp": StubERPAdapter,
        "crm": StubCRMAdapter,
        "mes": StubMESAdapter,
    }
    cls = mapping.get(system.lower())
    if cls is None:
        raise ValueError(f"unknown enterprise system: {system}")
    return cls(configured=configured)


def list_adapter_contracts() -> List[Dict[str, Any]]:
    return [
        {
            "system": "erp",
            "phases": ["read_only", "prefill", "approved_low_risk_write"],
            "external_gate": "customer_erp_spec_and_credentials",
        },
        {
            "system": "crm",
            "phases": ["read_only", "prefill", "approved_low_risk_write"],
            "external_gate": "customer_crm_spec_and_credentials",
        },
        {
            "system": "mes",
            "phases": ["read_only", "prefill"],
            "external_gate": "customer_mes_spec_and_credentials",
        },
    ]
