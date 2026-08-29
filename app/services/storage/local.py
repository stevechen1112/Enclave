"""本機檔案系統後端（預設；地端與開發用）。

行為與抽象層引入前完全一致：物件存放在 ``UPLOAD_DIR/<tenant_id>/``，
content_uri 為絕對路徑（向後相容既有 ``documents.file_path`` 語意）。
"""
from __future__ import annotations

import hashlib
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

    def _multipart_dir(self, key: str) -> str:
        validate_storage_key(key)
        tenant, filename = key.split("/", 1)
        target = os.path.abspath(os.path.join(self._root, ".multipart", tenant, filename))
        multipart_root = os.path.abspath(os.path.join(self._root, ".multipart"))
        if not target.startswith(multipart_root + os.sep):
            raise ValueError("multipart path escapes root")
        return target

    def create_multipart(self, key: str) -> str:
        target = self._multipart_dir(key)
        os.makedirs(target, exist_ok=True)
        return key

    def upload_part(self, key: str, upload_id: str, part_number: int, source_path: str) -> str:
        if upload_id != key or part_number < 1:
            raise ValueError("invalid local multipart identity")
        target_dir = self._multipart_dir(key)
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, f"{part_number:08d}.part")
        shutil.copyfile(source_path, target)
        digest = hashlib.sha256()
        with open(target, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def complete_multipart(self, key: str, upload_id: str, parts: list[tuple[int, str]]) -> str:
        if upload_id != key:
            raise ValueError("invalid local multipart identity")
        destination = self._path(key)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        temporary = destination + ".assembling"
        try:
            with open(temporary, "wb") as output:
                for number, _etag in sorted(parts):
                    with open(os.path.join(self._multipart_dir(key), f"{number:08d}.part"), "rb") as source:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
            os.replace(temporary, destination)
            shutil.rmtree(self._multipart_dir(key), ignore_errors=True)
            return destination
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    def abort_multipart(self, key: str, upload_id: str) -> None:
        if upload_id != key:
            raise ValueError("invalid local multipart identity")
        shutil.rmtree(self._multipart_dir(key), ignore_errors=True)
