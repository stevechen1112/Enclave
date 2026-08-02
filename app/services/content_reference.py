"""Resolve immutable content references for downstream adapters (signed URL / file ref)."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple
from uuid import UUID


def build_content_reference(
    file_path: str,
    tenant_id: UUID,
    document_id: UUID,
) -> Tuple[str, Dict[str, Any]]:
    """
    Build an Enclave content reference instead of passing raw paths to sidecars.
    Adapters resolve via metadata['file_path'] or HTTP signed URL when configured.
    """
    ref = f"enclave-ref://{tenant_id}/{document_id}"
    return ref, {
        "file_path": file_path,
        "tenant_id": str(tenant_id),
        "document_id": str(document_id),
        "resolver": "enclave",
    }


def resolve_content_bytes(
    content_uri: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> bytes:
    """Resolve file bytes from reference URI and metadata."""
    meta = metadata or {}
    if meta.get("file_bytes"):
        return meta["file_bytes"]

    file_path = meta.get("file_path")
    if file_path and os.path.isfile(file_path):
        with open(file_path, "rb") as f:
            return f.read()

    if content_uri.startswith("file://"):
        path = content_uri[7:]
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()

    if os.path.isfile(content_uri):
        with open(content_uri, "rb") as f:
            return f.read()

    if content_uri.startswith("enclave-ref://"):
        path = meta.get("file_path")
        if path and os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()

    raise ValueError(f"Cannot resolve content reference: {content_uri[:120]}")
