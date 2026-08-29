"""S3 相容物件儲存後端（R2／Linode Objects／AWS S3／MinIO；雲端形態用）。

content_uri 格式：``s3://<bucket>/<tenant_id>/<document_id>.<ext>``。
所有操作強制經 ``validate_storage_key``——key 必須帶租戶前綴，
從後端層杜絕跨租戶物件操作（ADR-011 措施 4）。
"""
from __future__ import annotations

from app.services.storage import validate_storage_key


class S3CompatibleBackend:
    name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        access_key: str,
        secret_key: str,
        endpoint_url: str | None = None,
        region: str = "auto",
    ):
        if not bucket:
            raise ValueError("S3_BUCKET is required for s3 storage backend")
        import boto3

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    def _uri(self, key: str) -> str:
        return f"s3://{self._bucket}/{key}"

    def put(self, key: str, source_path: str) -> str:
        validate_storage_key(key)
        self._client.upload_file(source_path, self._bucket, key)
        return self._uri(key)

    def get_to_file(self, key: str, dest_path: str) -> str:
        validate_storage_key(key)
        import os

        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        self._client.download_file(self._bucket, key, dest_path)
        return dest_path

    def get_bytes(self, key: str) -> bytes:
        validate_storage_key(key)
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def delete(self, key: str) -> None:
        validate_storage_key(key)
        # S3 delete 對不存在 key 亦回成功——天然冪等
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        validate_storage_key(key)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        validate_storage_key(key)
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires,
        )

    def create_multipart(self, key: str) -> str:
        validate_storage_key(key)
        response = self._client.create_multipart_upload(Bucket=self._bucket, Key=key)
        return str(response["UploadId"])

    def upload_part(self, key: str, upload_id: str, part_number: int, source_path: str) -> str:
        validate_storage_key(key)
        if part_number < 1:
            raise ValueError("part number must be positive")
        with open(source_path, "rb") as body:
            response = self._client.upload_part(
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
                PartNumber=part_number,
                Body=body,
            )
        return str(response["ETag"])

    def complete_multipart(self, key: str, upload_id: str, parts: list[tuple[int, str]]) -> str:
        validate_storage_key(key)
        self._client.complete_multipart_upload(
            Bucket=self._bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": [{"PartNumber": number, "ETag": etag} for number, etag in sorted(parts)]},
        )
        return self._uri(key)

    def abort_multipart(self, key: str, upload_id: str) -> None:
        validate_storage_key(key)
        self._client.abort_multipart_upload(Bucket=self._bucket, Key=key, UploadId=upload_id)
