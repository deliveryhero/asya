"""S3 buffered last-write-wins connector.

Reads configuration from environment variables:
    STATE_BUCKET      - S3 bucket name (required)
    STATE_PREFIX      - Key prefix inside the bucket (optional, default "")
    AWS_REGION        - AWS region (optional, default "us-east-1")
    AWS_ENDPOINT_URL  - Custom endpoint for MinIO/LocalStack (optional)
"""

import io
import logging
import os
from typing import Any, BinaryIO

import boto3
from botocore.exceptions import ClientError

from asya_state_proxy.connectors._query import ObjectStoreQueryMixin, _safe_sql_str, configure_s3_httpfs
from asya_state_proxy.connectors._s3_xattr import S3XattrMixin
from asya_state_proxy.interface import KeyMeta, ListResult, StateProxyConnector


logger = logging.getLogger("asya.state-proxy")


class S3BufferedLWW(ObjectStoreQueryMixin, S3XattrMixin, StateProxyConnector):
    """Last-write-wins S3 connector. Full body is buffered in memory."""

    def __init__(self) -> None:
        bucket = os.environ.get("STATE_BUCKET")
        if not bucket:
            raise RuntimeError("STATE_BUCKET environment variable is required")

        self._bucket = bucket
        self._prefix = os.environ.get("STATE_PREFIX", "")
        self._region = os.environ.get("AWS_REGION", "us-east-1")
        self._endpoint_url = os.environ.get("AWS_ENDPOINT_URL")

        kwargs: dict = {"region_name": self._region}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url

        self._s3 = boto3.client("s3", **kwargs)
        logger.info(
            "S3BufferedLWW connector initialised: bucket=%s prefix=%r region=%s endpoint=%s",
            bucket,
            self._prefix,
            self._region,
            self._endpoint_url or "(aws)",
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
        """Fetch object from S3 and return as in-memory stream."""
        full_key = self._full_key(key)
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=full_key)
            body = response["Body"].read()
            logger.debug("read key=%s size=%d", key, len(body))
            return io.BytesIO(body)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Key not found: {key}") from exc
            raise

    def write(self, key: str, data: BinaryIO, size: int | None = None, *, exclusive: bool = False) -> None:
        """Write object to S3 using last-write-wins semantics.

        When exclusive=True, uses IfNoneMatch='*' for atomic create-if-absent.
        """
        full_key = self._full_key(key)
        body = data.read()
        put_kwargs: dict = {"Bucket": self._bucket, "Key": full_key, "Body": body}
        if exclusive:
            put_kwargs["IfNoneMatch"] = "*"
        try:
            self._s3.put_object(**put_kwargs)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "PreconditionFailed":
                raise FileExistsError(f"Exclusive create failed: key={key} already exists") from exc
            raise
        logger.debug("write key=%s size=%d", key, len(body))

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
        """Delete object from S3. Raises FileNotFoundError if it does not exist."""
        full_key = self._full_key(key)
        # S3 DeleteObject does not error on missing keys, so check first.
        if not self.exists(key):
            raise FileNotFoundError(f"Key not found: {key}")
        self._s3.delete_object(Bucket=self._bucket, Key=full_key)
        logger.debug("delete key=%s", key)

    def _setup_duckdb_source(self, conn: Any, prefix: str, tmpdir: str) -> bool:
        """Override: use DuckDB httpfs to read S3 objects directly (no temp files).

        DuckDB streams from S3 without loading all objects into memory; the caller's
        LIMIT clause is pushed down so only the needed chunks are fetched.
        """
        configure_s3_httpfs(conn, self._region, self._endpoint_url)

        _safe_sql_str(prefix, "prefix")

        full_prefix = f"{self._prefix}/{prefix}" if self._prefix else prefix
        glob = f"s3://{self._bucket}/{full_prefix}**"

        sql = f"CREATE VIEW _tmp AS SELECT filename, content FROM read_text('{glob}') WHERE content IS NOT NULL"  # nosec B608  # nosemgrep
        conn.execute(sql)
        count = conn.execute("SELECT COUNT(*) FROM _tmp").fetchone()[0]
        logger.debug("query/httpfs: prefix=%r glob=%r count=%d", prefix, glob, count)
        return count == 0
