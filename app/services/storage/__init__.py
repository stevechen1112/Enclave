"""StorageBackend 工廠與 key 規約（ADR-011）。

key 格式：``<tenant_id>/<document_id><ext>``——租戶前綴是強制性的，
``build_storage_key`` 是唯一合法的 key 產生點；後端收到不符規約的 key
必須 raise（fail-closed），不得靜默接受。
"""
from __future__ import annotations

import re
import time
from typing import Optional
from uuid import UUID

from app.config import settings
from app.services.storage.base import StorageBackend

_KEY_RE = re.compile(r"^[0-9a-fA-F-]{36}/[0-9a-fA-F-]{36}\.[A-Za-z0-9]{1,16}$")


def build_storage_key(tenant_id: UUID, document_id: UUID, file_ext: str) -> str:
    """產生租戶前綴的物件 key（唯一合法產生點）。"""
    ext = (file_ext or "").lower().lstrip(".")
    if not ext or not re.fullmatch(r"[a-z0-9]{1,16}", ext):
        raise ValueError(f"invalid file extension for storage key: {file_ext!r}")
    return f"{tenant_id}/{document_id}.{ext}"


def validate_storage_key(key: str) -> None:
    """後端共用的 key 規約檢查；不符即 raise（fail-closed）。"""
    if not _KEY_RE.fullmatch(key or ""):
        raise ValueError(f"storage key violates tenant-prefix convention: {key!r}")


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """``s3://bucket/key`` → (bucket, key)。"""
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 uri: {uri[:80]!r}")
    rest = uri[5:]
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError(f"malformed s3 uri: {uri[:80]!r}")
    return bucket, key


def assert_key_matches_tenant(key: str, tenant_id: str) -> None:
    """防禦性檢查：物件 key 的租戶前綴必須與操作租戶一致。

    RLS 只約束 DB 層；物件儲存層的跨租戶 key 讀取必須在應用層擋下。
    任何「以 A 租戶身分操作 B 租戶 key」的嘗試都是資料外洩或攻擊訊號，
    一律 raise（fail-closed），不得靜默放行。
    """
    if not str(key).startswith(f"{tenant_id}/"):
        raise ValueError(
            f"storage key tenant prefix mismatch: tenant={tenant_id}, key={str(key)[:80]}"
        )


_backend: Optional[StorageBackend] = None


class _ObservedStorageBackend:
    def __init__(self, delegate: StorageBackend):
        self._delegate = delegate
        self.name = delegate.name

    def _call(self, operation: str, *args):
        started = time.perf_counter()
        ok = False
        try:
            result = getattr(self._delegate, operation)(*args)
            ok = True
            return result
        finally:
            try:
                from app.observability.business_metrics import record_object_io

                record_object_io(
                    backend=self.name,
                    operation=operation,
                    duration_seconds=time.perf_counter() - started,
                    ok=ok,
                )
            except Exception:
                pass

    def put(self, key: str, source_path: str) -> str:
        return self._call("put", key, source_path)

    def get_to_file(self, key: str, dest_path: str) -> str:
        return self._call("get_to_file", key, dest_path)

    def get_bytes(self, key: str) -> bytes:
        return self._call("get_bytes", key)

    def delete(self, key: str) -> None:
        self._call("delete", key)

    def exists(self, key: str) -> bool:
        return self._call("exists", key)

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        return self._call("presigned_url", key, expires)

    def create_multipart(self, key: str) -> str:
        return self._call("create_multipart", key)

    def upload_part(self, key: str, upload_id: str, part_number: int, source_path: str) -> str:
        return self._call("upload_part", key, upload_id, part_number, source_path)

    def complete_multipart(self, key: str, upload_id: str, parts: list[tuple[int, str]]) -> str:
        return self._call("complete_multipart", key, upload_id, parts)

    def abort_multipart(self, key: str, upload_id: str) -> None:
        self._call("abort_multipart", key, upload_id)


def get_storage_backend() -> StorageBackend:
    """依 ``STORAGE_BACKEND`` 設定回傳後端單例（local 預設，行為與舊版一致）。"""
    global _backend
    if _backend is not None:
        return _backend

    kind = str(getattr(settings, "STORAGE_BACKEND", "local") or "local").lower()
    if kind == "local":
        from app.services.storage.local import LocalFilesystemBackend

        _backend = _ObservedStorageBackend(
            LocalFilesystemBackend(root=settings.UPLOAD_DIR)
        )
    elif kind in ("s3", "s3_compatible", "r2"):
        from app.services.storage.s3_compatible import S3CompatibleBackend

        _backend = _ObservedStorageBackend(
            S3CompatibleBackend(
                endpoint_url=settings.S3_ENDPOINT_URL or None,
                bucket=settings.S3_BUCKET,
                access_key=settings.S3_ACCESS_KEY,
                secret_key=settings.S3_SECRET_KEY,
                region=settings.S3_REGION or "auto",
            )
        )
    else:
        raise ValueError(f"unknown STORAGE_BACKEND: {kind!r}")
    return _backend


def reset_storage_backend() -> None:
    """測試用：清除後端單例快取。"""
    global _backend
    _backend = None
