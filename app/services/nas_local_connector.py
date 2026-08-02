"""
NAS/SMB / local filesystem connector.

第一批 GA 連接器：在地端掃描目錄（Windows UNC 路徑或本機路徑），
產出 connector resources + ACL 投影，無需 OAuth。
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log", ".xml", ".html", ".htm"}
_DOC_EXTS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".rtf"}


def scan_local_nas(
    root_path: str,
    *,
    max_files: int = 200,
    principal_external_id: str = "nas-local-reader",
) -> Dict[str, Any]:
    """
    掃描 root_path，回傳 connector sync 相容結構。
    """
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        return {
            "status": "error",
            "error": f"nas_root_not_found:{root_path}",
        }

    resources: List[Dict[str, Any]] = []
    acl_entries: List[Dict[str, Any]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (_TEXT_EXTS | _DOC_EXTS):
            continue
        if len(resources) >= max_files:
            break

        try:
            data = path.read_bytes()
        except OSError as exc:
            logger.warning("skip unreadable %s: %s", path, exc)
            continue

        content_hash = hashlib.sha256(data).hexdigest()
        rel = str(path.relative_to(root)).replace("\\", "/")
        source_record_id = f"nas:{rel}"

        resources.append({
            "source_record_id": source_record_id,
            "title": path.name,
            "content_uri": path.resolve().as_uri() if hasattr(path, "as_uri") else f"file://{path.resolve()}",
            "file_path": str(path.resolve()),
            "mime_type": _guess_mime(path.suffix),
            "content_hash": content_hash,
            "source_version": str(int(path.stat().st_mtime)),
            "metadata": {
                "source": "nas_smb",
                "path": rel,
                "size": len(data),
            },
        })
        acl_entries.append({
            "provider": "nas_smb",
            "principal_external_id": principal_external_id,
            "principal_type": "user",
            "source_record_id": source_record_id,
            "effect": "allow",
            "permission": "read",
        })

    return {
        "status": "completed",
        "mode": "nas_local",
        "resources": resources,
        "acl_entries": acl_entries,
        "cursor": f"nas-scan:{len(resources)}:{int(root.stat().st_mtime)}",
    }


def _guess_mime(suffix: str) -> str:
    mapping = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".csv": "text/csv",
        ".json": "application/json",
    }
    return mapping.get(suffix.lower(), "application/octet-stream")
