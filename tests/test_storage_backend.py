"""StorageBackend 合約測試（ADR-011）。

涵蓋：key 規約（租戶前綴強制）、local 後端行為與舊版相容、
S3 後端（mock boto3）、content_reference 的 s3:// 解析、
上傳端點的 content_uri 持久化、worker 的 s3:// 暫存下載。
"""

import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

sys.path.insert(0, ".")

from app.services.storage import (
    assert_key_matches_tenant,
    build_storage_key,
    get_storage_backend,
    parse_s3_uri,
    reset_storage_backend,
    validate_storage_key,
)


TENANT = uuid4()
DOC = uuid4()


class TestStorageKey(unittest.TestCase):
    def test_key_format(self):
        key = build_storage_key(TENANT, DOC, ".pdf")
        self.assertEqual(key, f"{TENANT}/{DOC}.pdf")

    def test_ext_normalized(self):
        self.assertEqual(build_storage_key(TENANT, DOC, "PDF"), f"{TENANT}/{DOC}.pdf")

    def test_invalid_ext_rejected(self):
        for bad in ("", ".", "../x", "p f", "pdf;rm"):
            with self.assertRaises(ValueError):
                build_storage_key(TENANT, DOC, bad)

    def test_validate_accepts_built_key(self):
        validate_storage_key(build_storage_key(TENANT, DOC, ".docx"))

    def test_validate_rejects_no_tenant_prefix(self):
        for bad in (
            "",
            "file.pdf",
            f"{DOC}.pdf",
            f"a/b/c.pdf",
            f"../{TENANT}/{DOC}.pdf",
            f"{TENANT}/{DOC}.pdf/extra",
        ):
            with self.assertRaises(ValueError):
                validate_storage_key(bad)


class TestParseS3Uri(unittest.TestCase):
    def test_roundtrip(self):
        bucket, key = parse_s3_uri(f"s3://mybucket/{TENANT}/{DOC}.pdf")
        self.assertEqual(bucket, "mybucket")
        self.assertEqual(key, f"{TENANT}/{DOC}.pdf")

    def test_rejects_non_s3(self):
        with self.assertRaises(ValueError):
            parse_s3_uri("/local/path/file.pdf")

    def test_rejects_malformed(self):
        for bad in ("s3://", "s3://bucket", "s3://bucket/"):
            with self.assertRaises(ValueError):
                parse_s3_uri(bad)


class TestLocalBackend(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        from app.services.storage.local import LocalFilesystemBackend

        self.backend = LocalFilesystemBackend(root=self.root)
        self.key = build_storage_key(TENANT, DOC, ".txt")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def _write_tmp(self, content: bytes) -> str:
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        return path

    def test_put_get_roundtrip(self):
        src = self._write_tmp(b"hello enclave")
        uri = self.backend.put(self.key, src)
        # local 後端 content_uri = 絕對路徑（向後相容）
        self.assertTrue(os.path.isabs(uri))
        self.assertFalse(os.path.exists(src))  # put 後暫存被搬走
        self.assertEqual(self.backend.get_bytes(self.key), b"hello enclave")
        self.assertTrue(self.backend.exists(self.key))

    def test_get_to_file(self):
        src = self._write_tmp(b"worker-download")
        self.backend.put(self.key, src)
        dest = os.path.join(self.root, "dl", "copy.txt")
        self.backend.get_to_file(self.key, dest)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), b"worker-download")

    def test_delete_idempotent(self):
        src = self._write_tmp(b"x")
        self.backend.put(self.key, src)
        self.backend.delete(self.key)
        self.assertFalse(self.backend.exists(self.key))
        self.backend.delete(self.key)  # 不存在亦成功

    def test_path_traversal_blocked(self):
        with self.assertRaises(ValueError):
            self.backend.get_bytes("../outside.txt")

    def test_presigned_url_is_file_uri(self):
        src = self._write_tmp(b"x")
        uri = self.backend.put(self.key, src)
        self.assertTrue(self.backend.presigned_url(self.key).startswith("file://"))
        self.assertIn(uri, self.backend.presigned_url(self.key))


class TestS3Backend(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        fake_boto3 = types.SimpleNamespace(
            client=MagicMock(return_value=self.mock_client)
        )
        with patch.dict(sys.modules, {"boto3": fake_boto3}):
            from app.services.storage.s3_compatible import S3CompatibleBackend

            self.backend = S3CompatibleBackend(
                bucket="enclave-docs",
                access_key="ak",
                secret_key="sk",
                endpoint_url="https://example.r2.dev",
            )
        self.key = build_storage_key(TENANT, DOC, ".pdf")

    def test_requires_bucket(self):
        from app.services.storage.s3_compatible import S3CompatibleBackend

        with self.assertRaises(ValueError):
            S3CompatibleBackend(bucket="", access_key="a", secret_key="s")

    def test_put_returns_s3_uri(self):
        src = tempfile.mktemp()
        with open(src, "wb") as f:
            f.write(b"pdf-bytes")
        uri = self.backend.put(self.key, src)
        self.assertEqual(uri, f"s3://enclave-docs/{self.key}")
        self.mock_client.upload_file.assert_called_once_with(
            src, "enclave-docs", self.key
        )
        os.remove(src)

    def test_all_ops_validate_key(self):
        for op in (
            lambda: self.backend.put("no-prefix.pdf", "x"),
            lambda: self.backend.get_bytes("no-prefix.pdf"),
            lambda: self.backend.delete("no-prefix.pdf"),
            lambda: self.backend.exists("no-prefix.pdf"),
            lambda: self.backend.presigned_url("no-prefix.pdf"),
            lambda: self.backend.get_to_file("no-prefix.pdf", "y"),
        ):
            with self.assertRaises(ValueError):
                op()

    def test_get_bytes(self):
        body = MagicMock()
        body.read.return_value = b"remote-bytes"
        self.mock_client.get_object.return_value = {"Body": body}
        self.assertEqual(self.backend.get_bytes(self.key), b"remote-bytes")

    def test_exists_head_object(self):
        self.mock_client.head_object.return_value = {}
        self.assertTrue(self.backend.exists(self.key))
        self.mock_client.head_object.side_effect = RuntimeError("404")
        self.assertFalse(self.backend.exists(self.key))

    def test_presigned_url(self):
        self.mock_client.generate_presigned_url.return_value = "https://signed"
        url = self.backend.presigned_url(self.key, expires=60)
        self.assertEqual(url, "https://signed")
        _, kwargs = self.mock_client.generate_presigned_url.call_args
        self.assertEqual(kwargs["Params"]["Key"], self.key)
        self.assertEqual(kwargs["ExpiresIn"], 60)


class TestFactory(unittest.TestCase):
    def tearDown(self):
        reset_storage_backend()

    def test_default_local(self):
        reset_storage_backend()
        with patch("app.services.storage.settings") as s:
            s.STORAGE_BACKEND = "local"
            s.UPLOAD_DIR = tempfile.mkdtemp()
            backend = get_storage_backend()
        self.assertEqual(backend.name, "local")

    def test_unknown_backend_rejected(self):
        reset_storage_backend()
        with patch("app.services.storage.settings") as s:
            s.STORAGE_BACKEND = "ftp"
            with self.assertRaises(ValueError):
                get_storage_backend()


class TestKeyTenantGuard(unittest.TestCase):
    """物件儲存層的跨租戶防線（RLS 只管 DB，管不到 object key）。"""

    def test_matching_prefix_passes(self):
        key = build_storage_key(TENANT, DOC, ".pdf")
        assert_key_matches_tenant(key, str(TENANT))  # 不應 raise

    def test_other_tenant_key_rejected(self):
        other = uuid4()
        key = build_storage_key(other, DOC, ".pdf")
        with self.assertRaises(ValueError):
            assert_key_matches_tenant(key, str(TENANT))

    def test_similar_prefix_not_fooled(self):
        # 前綴比對必須含斜線邊界，避免 "abc" 匹配 "abcdef/..."
        with self.assertRaises(ValueError):
            assert_key_matches_tenant(f"{TENANT}evil/{DOC}.pdf", str(TENANT))


class TestUploadPutFailure(unittest.IsolatedAsyncioTestCase):
    """storage put 失敗時，已 commit 的文件列必須 tombstone，不留孤兒記錄。"""

    async def test_put_failure_tombstones_document(self):
        from app.api.v1.endpoints import documents as docs_ep

        tenant = uuid4()
        doc_id = uuid4()
        user = types.SimpleNamespace(
            tenant_id=tenant, id=uuid4(), role="admin", is_superuser=False
        )
        created_doc = types.SimpleNamespace(id=doc_id, file_path=None)

        # read 第一次回內容、第二次回 EOF
        class FakeUpload2:
            filename = "report.pdf"
            _calls = 0

            async def read(self, n):
                self._calls += 1
                return b"pdf-bytes" if self._calls == 1 else b""

            async def close(self):
                return None

        tmp_root = tempfile.mkdtemp()
        backend = MagicMock()
        backend.put.side_effect = RuntimeError("s3 unreachable")

        with (
            patch.object(docs_ep, "check_document_permission"),
            patch.object(
                docs_ep.crud_tenant, "check_quota", return_value={"allowed": True}
            ),
            patch.object(
                docs_ep.crud_tenant,
                "check_storage_quota",
                return_value={"allowed": True},
            ),
            patch.object(docs_ep.settings, "UPLOAD_DIR", tmp_root),
            patch.object(docs_ep.settings, "MAX_FILE_SIZE", 10 * 1024 * 1024),
            patch(
                "app.services.document_parser.DocumentParser.detect_file_type",
                return_value="pdf",
            ),
            patch.object(docs_ep.crud_document, "create", return_value=created_doc),
            patch.object(docs_ep.crud_document, "tombstone") as tombstone_mock,
            patch("app.services.storage.get_storage_backend", return_value=backend),
            patch.object(docs_ep.process_document_task, "delay") as delay_mock,
        ):
            db = MagicMock()
            from fastapi import HTTPException

            with self.assertRaises(HTTPException) as raised:
                await docs_ep.upload_document(
                    db=db, file=FakeUpload2(), current_user=user
                )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("資料未發布", raised.exception.detail)

        tombstone_mock.assert_called_once()
        _, kwargs = tombstone_mock.call_args
        self.assertEqual(kwargs.get("reason"), "storage_put_failed")
        delay_mock.assert_not_called()  # 失敗不得觸發解析任務

        import shutil

        shutil.rmtree(tmp_root, ignore_errors=True)


class TestUploadSpoolFailure(unittest.IsolatedAsyncioTestCase):
    """Local spool failures must be explicit and must not create document rows."""

    async def test_spool_directory_failure_returns_safe_503(self):
        from fastapi import HTTPException

        from app.api.v1.endpoints import documents as docs_ep

        user = types.SimpleNamespace(
            tenant_id=uuid4(), id=uuid4(), role="admin", is_superuser=False
        )

        class FakeUpload:
            filename = "report.pdf"
            closed = False

            async def close(self):
                self.closed = True

        upload = FakeUpload()
        with (
            patch.object(docs_ep, "check_document_permission"),
            patch.object(
                docs_ep.crud_tenant, "check_quota", return_value={"allowed": True}
            ),
            patch(
                "app.services.document_parser.DocumentParser.detect_file_type",
                return_value="pdf",
            ),
            patch.object(docs_ep.os, "makedirs", side_effect=PermissionError("denied")),
            patch.object(docs_ep.crud_document, "create") as create_mock,
        ):
            with self.assertRaises(HTTPException) as raised:
                await docs_ep.upload_document(
                    db=MagicMock(), file=upload, current_user=user
                )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("資料未發布", raised.exception.detail)
        self.assertTrue(upload.closed)
        create_mock.assert_not_called()


class TestContentReferenceS3(unittest.TestCase):
    def test_resolve_s3_uri_via_backend(self):
        from app.services import content_reference

        fake_backend = MagicMock()
        fake_backend.get_bytes.return_value = b"from-s3"
        key = build_storage_key(TENANT, DOC, ".pdf")
        with patch(
            "app.services.storage.get_storage_backend", return_value=fake_backend
        ):
            data = content_reference.resolve_content_bytes(f"s3://bucket/{key}")
        self.assertEqual(data, b"from-s3")
        fake_backend.get_bytes.assert_called_once_with(key)

    def test_local_path_still_works(self):
        from app.services import content_reference

        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            f.write(b"local-bytes")
        try:
            self.assertEqual(
                content_reference.resolve_content_bytes(path), b"local-bytes"
            )
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
