"""Connector credential storage — outside uploads/ with Fernet envelope encryption."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict

# Repo root: app/services/credential_vault.py → parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _REPO_ROOT / "var" / "credentials"


def get_credential_dir() -> Path:
    """
    Resolve credential vault directory.

    Priority:
      1. CONNECTOR_CREDENTIAL_DIR
      2. var/credentials (not under uploads/)
    """
    override = os.getenv("CONNECTOR_CREDENTIAL_DIR", "").strip()
    if override:
        return Path(override)
    return _DEFAULT_DIR


def ensure_credential_dir() -> Path:
    path = get_credential_dir()
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    uploads = (_REPO_ROOT / "uploads").resolve()
    try:
        resolved.relative_to(uploads)
    except ValueError:
        return path
    raise ValueError(
        f"CONNECTOR_CREDENTIAL_DIR must not be under uploads/: {resolved}"
    )


def _fernet():
    """Derive Fernet key from SECRET_KEY (or CONNECTOR_CREDENTIAL_KEY)."""
    from cryptography.fernet import Fernet

    raw = (
        os.getenv("CONNECTOR_CREDENTIAL_KEY", "").strip()
        or os.getenv("SECRET_KEY", "").strip()
        or "enclave-dev-only-credential-key"
    )
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal_credential_payload(payload: Dict[str, Any]) -> bytes:
    """Encrypt JSON payload; on-disk format is opaque ciphertext."""
    plain = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _fernet().encrypt(plain)


def open_credential_blob(blob: bytes) -> Dict[str, Any]:
    """Decrypt vault blob back to dict."""
    plain = _fernet().decrypt(blob)
    return json.loads(plain.decode("utf-8"))


def write_credential_file(path: Path, payload: Dict[str, Any]) -> None:
    path.write_bytes(seal_credential_payload(payload))
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def read_credential_file(path: Path) -> Dict[str, Any]:
    data = path.read_bytes()
    # Backward compat: legacy plaintext JSON
    if data[:1] in (b"{", b"["):
        return json.loads(data.decode("utf-8"))
    return open_credential_blob(data)
