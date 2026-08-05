"""CG-CLAMAV 上傳掃毒測試。"""
import socket
from unittest.mock import MagicMock, patch

import pytest

from app.services.file_scan import (
    FileScanError,
    MalwareDetectedError,
    scan_bytes,
    scan_file_path,
)


class TestFileScanDisabled:
    def test_scan_bytes_noop_when_disabled(self, monkeypatch):
        monkeypatch.setattr("app.services.file_scan.settings.CLAMAV_ENABLED", False)
        scan_bytes(b"clean", "test.txt")  # no raise

    def test_scan_file_path_noop_when_disabled(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.services.file_scan.settings.CLAMAV_ENABLED", False)
        p = tmp_path / "a.txt"
        p.write_bytes(b"data")
        scan_file_path(str(p), "a.txt")


class TestFileScanEnabled:
    def test_malware_detected(self, monkeypatch):
        monkeypatch.setattr("app.services.file_scan.settings.CLAMAV_ENABLED", True)

        mock_sock = MagicMock()
        mock_sock.recv.return_value = b"stream: EICAR-Test-File FOUND\x00"
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("app.services.file_scan.socket.create_connection", return_value=mock_sock):
            with pytest.raises(MalwareDetectedError) as exc:
                scan_bytes(b"eicar", "bad.txt")
            assert "EICAR" in exc.value.signature

    def test_connection_failure_raises(self, monkeypatch):
        monkeypatch.setattr("app.services.file_scan.settings.CLAMAV_ENABLED", True)

        with patch(
            "app.services.file_scan.socket.create_connection",
            side_effect=OSError("connection refused"),
        ):
            with pytest.raises(FileScanError):
                scan_bytes(b"data", "x.txt")

    def test_clean_file_ok(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.services.file_scan.settings.CLAMAV_ENABLED", True)

        mock_sock = MagicMock()
        mock_sock.recv.return_value = b"stream: OK\x00"
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)

        p = tmp_path / "clean.txt"
        p.write_bytes(b"hello world")

        with patch("app.services.file_scan.socket.create_connection", return_value=mock_sock):
            scan_file_path(str(p), "clean.txt")


@pytest.mark.asyncio
async def test_upload_rejects_malware(client, superuser_headers, monkeypatch):
    """整合：啟用 ClamAV 時惡意檔案上傳回 400。"""
    from tests.conftest import create_tenant, create_user, login_user

    monkeypatch.setattr("app.config.settings.CLAMAV_ENABLED", True)
    monkeypatch.setattr("app.config.settings.CLAMAV_FAIL_CLOSED", True)

    t = await create_tenant(client, superuser_headers, {
        "name": "ClamAV", "tax_id": "CV01",
        "contact_name": "C", "contact_email": "c@cv01.com",
        "contact_phone": "0900000001", "plan": "team",
    })
    await create_user(client, superuser_headers, {
        "email": "owner@cv01.com", "password": "Owner123!",
        "full_name": "Owner", "role": "owner", "tenant_id": t["id"],
    })
    h = await login_user(client, "owner@cv01.com", "Owner123!")

    with patch(
        "app.services.file_scan.scan_file_path",
        side_effect=MalwareDetectedError("EICAR-Test-File"),
    ):
        r = await client.post(
            "/api/v1/documents/upload", headers=h,
            files={"file": ("eicar.txt", b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR", "text/plain")},
        )
    assert r.status_code == 400
    assert "安全掃描" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upload_fail_closed_on_scan_error(client, superuser_headers, monkeypatch):
    from tests.conftest import create_tenant, create_user, login_user

    monkeypatch.setattr("app.config.settings.CLAMAV_ENABLED", True)
    monkeypatch.setattr("app.config.settings.CLAMAV_FAIL_CLOSED", True)

    t = await create_tenant(client, superuser_headers, {
        "name": "ClamDown", "tax_id": "CV02",
        "contact_name": "C", "contact_email": "c@cv02.com",
        "contact_phone": "0900000002", "plan": "team",
    })
    await create_user(client, superuser_headers, {
        "email": "owner@cv02.com", "password": "Owner123!",
        "full_name": "Owner", "role": "owner", "tenant_id": t["id"],
    })
    h = await login_user(client, "owner@cv02.com", "Owner123!")

    with patch(
        "app.services.file_scan.scan_file_path",
        side_effect=FileScanError("clamd down"),
    ):
        r = await client.post(
            "/api/v1/documents/upload", headers=h,
            files={"file": ("ok.txt", b"hello", "text/plain")},
        )
    assert r.status_code == 503
