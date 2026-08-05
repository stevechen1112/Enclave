"""ClamAV 上傳掃毒（CG-CLAMAV）— INSTREAM 協定，fail-closed 可配置。"""
from __future__ import annotations

import socket
import struct
import time
from pathlib import Path

from app.config import settings


class FileScanError(Exception):
    """掃毒服務不可用或回應異常。"""


class MalwareDetectedError(FileScanError):
    def __init__(self, signature: str):
        super().__init__(signature)
        self.signature = signature


def _scan_instream(chunks_iter, *, filename: str) -> None:
    """以 INSTREAM 協定掃描位元組迭代器。"""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            sock = socket.create_connection(
                (settings.CLAMAV_HOST, settings.CLAMAV_PORT),
                timeout=settings.CLAMAV_TIMEOUT_SECONDS,
            )
            break
        except OSError as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise FileScanError(f"ClamAV scan failed for {filename}: {exc}") from exc
    else:
        raise FileScanError(f"ClamAV scan failed for {filename}: {last_exc}") from last_exc

    try:
        with sock:
            sock.sendall(b"zINSTREAM\0")
            for chunk in chunks_iter:
                if not chunk:
                    continue
                sock.sendall(struct.pack(">I", len(chunk)))
                sock.sendall(chunk)
            sock.sendall(struct.pack(">I", 0))

            response = b""
            while True:
                part = sock.recv(4096)
                if not part:
                    break
                response += part
                decoded_so_far = response.decode("utf-8", errors="replace").strip("\x00\r\n ")
                if decoded_so_far.endswith("FOUND") or decoded_so_far.endswith("OK"):
                    break

        decoded = response.decode("utf-8", errors="replace").strip("\x00\r\n ")
        if decoded.endswith("FOUND"):
            signature = decoded.split(":", 1)[-1].replace("FOUND", "").strip()
            raise MalwareDetectedError(signature or "malware")
        if not decoded.endswith("OK"):
            raise FileScanError(f"Unexpected ClamAV response for {filename}: {decoded or 'empty response'}")
    except MalwareDetectedError:
        raise
    except Exception as exc:
        raise FileScanError(f"ClamAV scan failed for {filename}: {exc}") from exc


def scan_bytes(data: bytes, filename: str = "upload") -> None:
    """掃描記憶體中的檔案內容。"""
    if not settings.CLAMAV_ENABLED:
        return

    chunk_size = 1024 * 1024

    def _iter():
        for start in range(0, len(data), chunk_size):
            yield data[start : start + chunk_size]

    _scan_instream(_iter(), filename=filename)


def scan_file_path(path: str, filename: str = "upload") -> None:
    """掃描磁碟上的檔案（串流讀取，避免大檔一次載入記憶體）。"""
    if not settings.CLAMAV_ENABLED:
        return

    chunk_size = 1024 * 1024
    p = Path(path)

    def _iter():
        with p.open("rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    _scan_instream(_iter(), filename=filename)
