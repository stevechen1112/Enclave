"""Immutable release identity shared by health, operations and deployment smoke tests."""

from __future__ import annotations

import os
from typing import Any

_UNKNOWN_VALUES = {"", "unknown", "dev", "local", "unset"}


def _value(name: str, default: str = "unknown") -> str:
    return os.getenv(name, default).strip() or default


def get_release_metadata() -> dict[str, Any]:
    """Return non-secret build identity injected while release images are built."""
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "release_id": _value("ENCLAVE_RELEASE_ID"),
        "source_commit": _value("ENCLAVE_SOURCE_COMMIT"),
        "source_dirty": _value("ENCLAVE_SOURCE_DIRTY"),
        "build_time": _value("ENCLAVE_BUILD_TIME"),
        "deployment_manifest_id": _value("ENCLAVE_DEPLOYMENT_MANIFEST_ID"),
        "schema_head": _value("ENCLAVE_SCHEMA_HEAD"),
        "route_contract_hash": _value("ENCLAVE_ROUTE_CONTRACT_HASH"),
        "backend_image_digest": _value("ENCLAVE_BACKEND_IMAGE_DIGEST"),
        "frontend_image_digest": _value("ENCLAVE_FRONTEND_IMAGE_DIGEST"),
    }
    required = (
        "release_id",
        "source_commit",
        "source_dirty",
        "build_time",
        "schema_head",
        "route_contract_hash",
    )
    metadata["identifiable"] = all(
        str(metadata[key]).lower() not in _UNKNOWN_VALUES for key in required
    )
    return metadata


def get_public_release_metadata() -> dict[str, Any]:
    """Safe subset exposed by the public health endpoint for parity checks."""
    metadata = get_release_metadata()
    return {
        key: metadata[key]
        for key in (
            "schema_version",
            "release_id",
            "source_commit",
            "source_dirty",
            "build_time",
            "deployment_manifest_id",
            "schema_head",
            "route_contract_hash",
            "identifiable",
        )
    }
