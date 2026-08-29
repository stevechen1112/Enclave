"""StorageBackend 介面定義（ADR-011）。

所有文件 bytes 的存取一律經此抽象層；部署形態由 ``STORAGE_BACKEND`` 決定。
key 永遠以 ``<tenant_id>/`` 開頭（見 ``build_storage_key``），後端實作
必須拒絕不帶租戶前綴的 key，從介面層杜絕跨租戶物件操作。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """物件儲存後端協定。

    - ``put``：從本機暫存檔上架，回傳 content_uri（local=絕對路徑；s3=s3://bucket/key）
    - ``get_to_file``：下載到本機路徑（worker 解析用）
    - ``get_bytes``：直接取 bytes（小檔／引用解析用）
    - ``delete``：刪除物件（撤權清除用；不存在視為成功，冪等）
    - ``exists``：存在性檢查
    - ``presigned_url``：預簽名下載 URL（local 後端回傳 file:// 路徑）
    """

    name: str

    def put(self, key: str, source_path: str) -> str:
        ...

    def get_to_file(self, key: str, dest_path: str) -> str:
        ...

    def get_bytes(self, key: str) -> bytes:
        ...

    def delete(self, key: str) -> None:
        ...

    def exists(self, key: str) -> bool:
        ...

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        ...

    def create_multipart(self, key: str) -> str:
        ...

    def upload_part(self, key: str, upload_id: str, part_number: int, source_path: str) -> str:
        ...

    def complete_multipart(self, key: str, upload_id: str, parts: list[tuple[int, str]]) -> str:
        ...

    def abort_multipart(self, key: str, upload_id: str) -> None:
        ...
