"""
NAS/SMB / local filesystem connector.

第一批 GA 連接器：在地端掃描目錄（Windows UNC 路徑或本機路徑），
產出 connector resources + ACL 投影，無需 OAuth。
"""
from __future__ import annotations

import hashlib
import logging
import json
from pathlib import Path
from typing import Any, Dict, List

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
    root = Path(root_path).resolve()
    if not root.exists() or not root.is_dir():
        return {
            "status": "error",
            "error": f"nas_root_not_found:{root_path}",
        }

    resources: List[Dict[str, Any]] = []
    acl_entries: List[Dict[str, Any]] = []

    eligible_paths: list[Path] = []
    for path in sorted(root.rglob("*")):
        # Never traverse a symlinked file out of the configured share root.
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in (_TEXT_EXTS | _DOC_EXTS):
            continue
        try:
            path.resolve().relative_to(root)
        except ValueError:
            continue
        eligible_paths.append(path)

    selected_paths = eligible_paths[:max_files]
    snapshot_complete = len(selected_paths) == len(eligible_paths)
    snapshot_hasher = hashlib.sha256()

    for path in selected_paths:

        try:
            data = path.read_bytes()
        except OSError as exc:
            logger.warning("skip unreadable %s: %s", path, exc)
            continue

        content_hash = hashlib.sha256(data).hexdigest()
        rel = str(path.relative_to(root)).replace("\\", "/")
        source_record_id = f"nas:{rel}"
        stat = path.stat()
        snapshot_hasher.update(
            f"{source_record_id}\0{content_hash}\0{stat.st_size}\n".encode("utf-8")
        )

        resources.append({
            "source_record_id": source_record_id,
            "title": path.name,
            "content_uri": path.resolve().as_uri() if hasattr(path, "as_uri") else f"file://{path.resolve()}",
            "file_path": str(path.resolve()),
            "mime_type": _guess_mime(path.suffix),
            "content_hash": content_hash,
            "source_version": str(stat.st_mtime_ns),
            "metadata": {
                "source": "nas_smb",
                "path": rel,
                "size": stat.st_size,
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

    snapshot_id = snapshot_hasher.hexdigest()
    cursor_payload = {
        "version": 1,
        "snapshot_id": snapshot_id,
        "resource_count": len(resources),
        "snapshot_complete": snapshot_complete,
    }
    cursor = "nas-v1:" + json.dumps(
        cursor_payload, sort_keys=True, separators=(",", ":")
    )
    return {
        "status": "completed",
        "mode": "nas_local",
        "resources": resources,
        "acl_entries": acl_entries,
        "cursor": cursor,
        "snapshot_id": snapshot_id,
        "snapshot_complete": snapshot_complete,
        "delete_semantics": "tombstone",
        "total_eligible": len(eligible_paths),
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
