"""S3 buffered compare-and-swap connector.

Reads configuration from environment variables:
    STATE_BUCKET      - S3 bucket name (required)
    STATE_PREFIX      - Key prefix inside the bucket (optional, default "")
    AWS_REGION        - AWS region (optional, default "us-east-1")
    AWS_ENDPOINT_URL  - Custom endpoint for MinIO/LocalStack (optional)
"""

import io
import logging
import os
from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from asya_state_proxy.interface import KeyMeta, ListResult, StateProxyConnector


logger = logging.getLogger("asya.state-proxy")


class S3BufferedCAS(StateProxyConnector):
    """Compare-and-swap S3 connector. Full body is buffered in memory.

    Maintains an in-memory ETag cache to detect concurrent modifications.
    When writing a key that was previously read, the write is conditional
    on the cached ETag matching the current S3 ETag. If the object was
    modified externally, the write raises FileExistsError.
    """

    def __init__(self) -> None:
        bucket = os.environ.get("STATE_BUCKET")
        if not bucket:
            raise RuntimeError("STATE_BUCKET environment variable is required")

        self._bucket = bucket
        self._prefix = os.environ.get("STATE_PREFIX", "")
        region = os.environ.get("AWS_REGION", "us-east-1")
        endpoint_url = os.environ.get("AWS_ENDPOINT_URL")

        kwargs: dict = {"region_name": region}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url

        self._s3 = boto3.client("s3", **kwargs)
        self._etags: dict[str, str] = {}
        logger.info(
            "S3BufferedCAS connector initialised: bucket=%s prefix=%r region=%s endpoint=%s",
            bucket,
            self._prefix,
            region,
            endpoint_url or "(aws)",
        )

    def _full_key(self, key: str) -> str:
        if self._prefix:
            return f"{self._prefix}/{key}"
        return key

    def _strip_prefix(self, full_key: str) -> str:
        """Remove the state prefix from a full S3 key."""
        if self._prefix and full_key.startswith(self._prefix + "/"):
            return full_key[len(self._prefix) + 1 :]
        return full_key

    def read(self, key: str) -> BinaryIO:
        """Fetch object from S3, cache ETag, and return as in-memory stream."""
        full_key = self._full_key(key)
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=full_key)
            body = response["Body"].read()
            self._etags[key] = response["ETag"]
            logger.debug("read key=%s size=%d etag=%s", key, len(body), response["ETag"])
            return io.BytesIO(body)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Key not found: {key}") from exc
            raise

    def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
        """Write object to S3 with CAS semantics when a prior ETag is cached.

        If the key was previously read, the write is conditional on the cached
        ETag matching the current S3 object ETag. If the condition fails (object
        was modified externally), FileExistsError is raised.

        If the key has never been read, the write is unconditional (new key path).
        """
        full_key = self._full_key(key)
        body = data.read()

        put_kwargs: dict = {"Bucket": self._bucket, "Key": full_key, "Body": body}
        cached_etag = self._etags.get(key)
        if cached_etag is not None:
            put_kwargs["IfMatch"] = cached_etag

        try:
            response = self._s3.put_object(**put_kwargs)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "PreconditionFailed":
                raise FileExistsError(f"CAS conflict: key={key} cached_etag={cached_etag}") from exc
            raise

        self._etags[key] = response["ETag"]
        logger.debug("write key=%s size=%d etag=%s", key, len(body), response["ETag"])

    def exists(self, key: str) -> bool:
        """Return True if the object exists in S3."""
        full_key = self._full_key(key)
        try:
            self._s3.head_object(Bucket=self._bucket, Key=full_key)
            return True
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("404", "NoSuchKey"):
                return False
            raise

    def stat(self, key: str) -> KeyMeta | None:
        """Return KeyMeta for the object, or None if it does not exist."""
        full_key = self._full_key(key)
        try:
            response = self._s3.head_object(Bucket=self._bucket, Key=full_key)
            size = response.get("ContentLength", 0)
            logger.debug("stat key=%s size=%d", key, size)
            return KeyMeta(size=size, is_file=True)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("404", "NoSuchKey"):
                return None
            raise

    def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
        """List objects under the given prefix."""
        full_prefix = self._full_key(key_prefix) if key_prefix else (self._prefix + "/" if self._prefix else "")

        paginator = self._s3.get_paginator("list_objects_v2")
        keys: list[str] = []
        prefixes: list[str] = []

        page_kwargs: dict = {"Bucket": self._bucket, "Prefix": full_prefix}
        if delimiter:
            page_kwargs["Delimiter"] = delimiter

        for page in paginator.paginate(**page_kwargs):
            for obj in page.get("Contents", []):
                keys.append(self._strip_prefix(obj["Key"]))
            for cp in page.get("CommonPrefixes", []):
                prefixes.append(self._strip_prefix(cp["Prefix"]))

        logger.debug("list prefix=%r keys=%d prefixes=%d", key_prefix, len(keys), len(prefixes))
        return ListResult(keys=keys, prefixes=prefixes)

    def delete(self, key: str) -> None:
        """Delete object from S3 and clear ETag cache. Raises FileNotFoundError if not found."""
        full_key = self._full_key(key)
        # S3 DeleteObject does not error on missing keys, so check first.
        if not self.exists(key):
            raise FileNotFoundError(f"Key not found: {key}")
        self._s3.delete_object(Bucket=self._bucket, Key=full_key)
        self._etags.pop(key, None)
        logger.debug("delete key=%s", key)
