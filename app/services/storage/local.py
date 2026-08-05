"""本機檔案系統後端（預設；地端與開發用）。

行為與抽象層引入前完全一致：物件存放在 ``UPLOAD_DIR/<tenant_id>/``，
content_uri 為絕對路徑（向後相容既有 ``documents.file_path`` 語意）。
"""
from __future__ import annotations

import os
import shutil

from app.services.storage import validate_storage_key


class LocalFilesystemBackend:
    name = "local"

    def __init__(self, root: str):
        self._root = os.path.abspath(root)

    def _path(self, key: str) -> str:
        validate_storage_key(key)
        path = os.path.abspath(os.path.join(self._root, key))
        # 防路徑穿越：解析後必須仍在 root 內
        if not path.startswith(self._root + os.sep):
            raise ValueError(f"storage key escapes root: {key!r}")
        return path

    def put(self, key: str, source_path: str) -> str:
        dest = self._path(key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            os.replace(source_path, dest)
        except OSError:
            # 跨裝置（例如 tmpfs → 資料碟）時退回複製
            shutil.copyfile(source_path, dest)
            os.remove(source_path)
        return dest

    def get_to_file(self, key: str, dest_path: str) -> str:
        src = self._path(key)
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        shutil.copyfile(src, dest_path)
        return dest_path

    def get_bytes(self, key: str) -> bytes:
        with open(self._path(key), "rb") as f:
            return f.read()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)

    def exists(self, key: str) -> bool:
        return os.path.isfile(self._path(key))

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        return "file://" + self._path(key)
