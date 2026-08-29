"""Stable connector SDK surface used by built-in and customer adapters."""

from app.platform.connectors.contracts import (
    ConnectorAuthExpired,
    ConnectorPage,
    ConnectorRateLimited,
    ConnectorResourceRecord,
    ConnectorSource,
    DeleteSemantics,
    retry_connector_call,
)

__all__ = [
    "ConnectorAuthExpired",
    "ConnectorPage",
    "ConnectorRateLimited",
    "ConnectorResourceRecord",
    "ConnectorSource",
    "DeleteSemantics",
    "retry_connector_call",
]
