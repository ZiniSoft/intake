from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import get_settings


class ObjectStorage(Protocol):
    def put(self, key: str, content: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def healthcheck(self) -> None: ...


class LocalObjectStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def put(self, key: str, content: bytes, content_type: str) -> None:
        del content_type
        destination = self.root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def delete(self, key: str) -> None:
        object_path = self.root / key
        if object_path.exists():
            object_path.unlink()

    def healthcheck(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


class SeaweedS3ObjectStorage:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.s3_access_key or not settings.s3_secret_key:
            raise RuntimeError("SeaweedFS S3 credentials are not configured")
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self._ensure_bucket()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def healthcheck(self) -> None:
        self._ensure_bucket()
        self.client.head_bucket(Bucket=self.bucket)


@lru_cache
def get_object_storage() -> ObjectStorage:
    settings = get_settings()
    if settings.storage_backend.lower() == "local":
        return LocalObjectStorage(settings.attachment_root)
    if settings.storage_backend.lower() in {"seaweedfs", "s3"}:
        return SeaweedS3ObjectStorage()
    raise RuntimeError(f"Unsupported storage backend: {settings.storage_backend}")
