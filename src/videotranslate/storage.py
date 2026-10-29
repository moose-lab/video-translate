"""Private object storage. Keys are opaque relative identifiers, never user paths."""

import io
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol

import boto3
from botocore.config import Config

from .config import Settings


class Storage(Protocol):
    def put(self, key: str, source: BinaryIO, content_type: str) -> None: ...
    def open(self, key: str, start: int = 0, end: int | None = None) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...


def validate_key(key: str) -> str:
    if (
        not key
        or len(key) > 255
        or key.startswith("/")
        or "\\" in key
        or ":" in key
        or any(ord(char) < 32 for char in key)
        or any(part in {"", ".", ".."} for part in key.split("/"))
    ):
        raise ValueError("Invalid storage key")
    return key


class _BoundedReader(io.BufferedReader):
    """Cap reads consistently with S3 Range responses without loading the object."""

    def __init__(self, raw, length: int):
        super().__init__(raw)
        self.remaining = length

    def read(self, size: int = -1) -> bytes:
        amount = self.remaining if size < 0 else min(size, self.remaining)
        data = super().read(amount)
        self.remaining -= len(data)
        return data


class LocalStorage:
    """Development/test adapter. The root must be owned exclusively by the service user."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, key: str) -> Path:
        path = (self.root / PurePosixPath(validate_key(key))).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Invalid storage key")
        return path

    def put(self, key: str, source: BinaryIO, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".upload-", delete=False
            ) as out:
                temporary = Path(out.name)
                shutil.copyfileobj(source, out, length=1024 * 1024)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def open(self, key: str, start: int = 0, end: int | None = None) -> BinaryIO:
        if start < 0 or (end is not None and end < start):
            raise ValueError("Invalid storage range")
        stream = self._path(key).open("rb", buffering=0)
        stream.seek(start)
        return stream if end is None else _BoundedReader(stream, end - start + 1)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Storage:
    """S3-compatible private adapter; bucket public access must be blocked by deployment policy."""

    def __init__(self, bucket: str, *, client):
        self.bucket, self.client = bucket, client

    def put(self, key: str, source: BinaryIO, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=validate_key(key), Body=source, ContentType=content_type
        )

    def open(self, key: str, start: int = 0, end: int | None = None) -> BinaryIO:
        params = {"Bucket": self.bucket, "Key": validate_key(key)}
        if start or end is not None:
            params["Range"] = f"bytes={start}-{end if end is not None else ''}"
        return self.client.get_object(**params)["Body"]

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=validate_key(key))


def make_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_root)
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 2, "mode": "standard"},
            connect_timeout=10,
            read_timeout=60,
        ),
    )
    return S3Storage(settings.s3_bucket, client=client)
