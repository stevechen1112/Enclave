"""
P3-1：Connector Materialize — 雲端 resource 下載到本機。

稽核文件 §9.3 關鍵斷點：
  雲端 connector 的 resource 若沒有本機 file_path，
  目前 materialize_to_documents() 不會自然進 Enclave canonical／RAGFlow。

  SharePoint／Drive → Enclave Document → RAGFlow → canonical chat

這條下載／materialize 管線需在真實客戶場景施工。

本模組補上「雲端 resource 下載器」：
  當 file_path 缺失或為遠端 URI（http://, https://, s3://）時，
  先下載到 UPLOAD_DIR/{tenant_id}/ 暫存，再將本機路徑餵給後續管線。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ResourceDownloader:
    """雲端 connector resource 下載器。

    支援的 URI 格式：
    - http:// / https:// — HTTP 下載
    - s3:// — S3 下載（透過 StorageBackend）
    - 本機路徑 — 直接驗證存在
    """

    def __init__(self, upload_dir: str = "./uploads", max_size_mb: int = 100, timeout: int = 300, auth_token: str = ""):
        self.upload_dir = Path(upload_dir)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.timeout = timeout
        self.auth_token = auth_token  # 用於 SharePoint/Drive 等需認證的下載

    def resolve_and_download(
        self,
        resource: Dict[str, Any],
        tenant_id: str,
    ) -> Optional[str]:
        """解析 resource 並下載到本機。

        Args:
            resource: connector resource dict，含 file_path, downloadPath, url, name 等
            tenant_id: 租戶 ID（用於隔離下載目錄）

        Returns:
            本機檔案路徑，或 None（下載失敗或無有效來源）
        """
        # 嘗試各種路徑欄位
        src = (
            resource.get("file_path")
            or resource.get("downloadPath")
            or resource.get("url")
            or resource.get("download_url")
        )

        if not src:
            logger.warning(f"Resource has no downloadable path: {resource.get('id', 'unknown')}")
            return None

        src = str(src).strip()

        # 本機路徑 — 直接驗證
        if not self._is_remote_uri(src):
            if Path(src).is_file():
                return src
            logger.warning(f"Local file not found: {src}")
            return None

        # 遠端 URI — 下載
        try:
            return self._download_remote(src, tenant_id, resource)
        except Exception as exc:
            logger.error(f"Failed to download {src}: {exc}")
            return None

    def _is_remote_uri(self, path: str) -> bool:
        """判斷是否為遠端 URI。"""
        parsed = urlparse(path)
        return parsed.scheme in ("http", "https", "s3", "ftp")

    def _download_remote(
        self,
        uri: str,
        tenant_id: str,
        resource: Dict[str, Any],
    ) -> Optional[str]:
        """下載遠端 resource 到本機。"""
        parsed = urlparse(uri)
        scheme = parsed.scheme

        # 建立租戶目錄
        dest_dir = self.upload_dir / tenant_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        # 決定檔名
        filename = resource.get("name") or resource.get("filename") or Path(parsed.path).name or "downloaded"
        # 安全化檔名（防止路徑穿越）
        filename = self._sanitize_filename(filename)
        dest_path = dest_dir / filename

        if scheme in ("http", "https"):
            return self._download_http(uri, dest_path)
        elif scheme == "s3":
            return self._download_s3(uri, dest_path)
        else:
            logger.warning(f"Unsupported URI scheme: {scheme}")
            return None

    def _download_http(self, url: str, dest_path: Path) -> Optional[str]:
        """HTTP/HTTPS 下載（支援認證標頭）。"""
        import httpx

        try:
            headers = {}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"

            with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
                with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        logger.warning(f"HTTP {resp.status_code} downloading {url}")
                        return None

                    # 檢查 Content-Length
                    content_length = resp.headers.get("content-length")
                    if content_length and int(content_length) > self.max_size_bytes:
                        logger.warning(
                            f"File too large: {content_length} bytes > {self.max_size_bytes} "
                            f"({url})"
                        )
                        return None

                    # 串流寫入
                    with open(dest_path, "wb") as f:
                        downloaded = 0
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if downloaded > self.max_size_bytes:
                                logger.warning(f"Download exceeded size limit: {url}")
                                dest_path.unlink(missing_ok=True)
                                return None

            logger.info(f"Downloaded {url} → {dest_path} ({dest_path.stat().st_size} bytes)")
            return str(dest_path)

        except Exception as exc:
            logger.error(f"HTTP download failed: {url} — {exc}")
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)
            return None

    def _download_s3(self, s3_uri: str, dest_path: Path) -> Optional[str]:
        """S3 下載（透過 StorageBackend）。"""
        try:
            from app.services.storage import get_storage_backend

            backend = get_storage_backend()
            # s3://bucket/key → backend.get_to_file(key, dest_path)
            parsed = urlparse(s3_uri)
            key = parsed.path.lstrip("/")

            # 檢查大小
            try:
                meta = backend.head(key)
                if meta and meta.get("size", 0) > self.max_size_bytes:
                    logger.warning(f"S3 object too large: {s3_uri}")
                    return None
            except Exception:
                pass  # head 失敗不阻塞，繼續嘗試下載

            backend.get_to_file(key, str(dest_path))
            logger.info(f"Downloaded {s3_uri} → {dest_path}")
            return str(dest_path)

        except Exception as exc:
            logger.error(f"S3 download failed: {s3_uri} — {exc}")
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)
            return None

    def _sanitize_filename(self, filename: str) -> str:
        """安全化檔名（防止路徑穿越）。"""
        # 只取檔名部分（去除任何路徑分隔符）
        filename = Path(filename).name
        # 限制長度
        if len(filename) > 200:
            stem = Path(filename).stem[:190]
            suffix = Path(filename).suffix
            filename = stem + suffix
        return filename or "downloaded"


# ── 單例 ──

_downloader: Optional[ResourceDownloader] = None


def get_resource_downloader() -> ResourceDownloader:
    global _downloader
    if _downloader is None:
        from app.config import settings
        _downloader = ResourceDownloader(
            upload_dir=settings.UPLOAD_DIR,
            max_size_mb=settings.CONNECTOR_MATERIALIZE_MAX_SIZE,
            timeout=settings.CONNECTOR_MATERIALIZE_TIMEOUT,
        )
    return _downloader