"""Shared xattr implementation for S3-based connectors.

All three S3 connectors (passthrough, buffered-cas, buffered-lww) expose the
same set of metadata attributes.  This mixin provides ``listxattr``,
``getxattr`` and ``setxattr`` so each connector only needs to inherit it.

Subclasses must provide ``self._bucket``, ``self._prefix``, ``self._s3``
(boto3 client), and ``_full_key(key) -> str``.
"""

import os


_S3_ATTRS = [
    "url",
    "presigned_url",
    "etag",
    "content_type",
    "version",
    "storage_class",
]
_S3_WRITABLE = {"content_type"}


class S3XattrMixin:
    """Mixin that adds xattr support for S3-backed connectors."""

    def listxattr(self, key: str) -> list[str]:
        return list(_S3_ATTRS)

    def getxattr(self, key: str, attr: str) -> str:
        full_key = self._full_key(key)  # type: ignore[attr-defined]
        bucket = self._bucket  # type: ignore[attr-defined]
        s3 = self._s3  # type: ignore[attr-defined]

        if attr == "url":
            return f"s3://{bucket}/{full_key}"

        if attr == "presigned_url":
            ttl = int(os.environ.get("STATE_PRESIGN_TTL", "3600"))
            return s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": full_key},
                ExpiresIn=ttl,
            )

        if attr in ("etag", "content_type", "version", "storage_class"):
            resp = s3.head_object(Bucket=bucket, Key=full_key)
            if attr == "etag":
                return resp["ETag"]
            if attr == "content_type":
                return resp.get("ContentType", "application/octet-stream")
            if attr == "version":
                return resp.get("VersionId", "")
            # storage_class
            return resp.get("StorageClass", "STANDARD")

        raise KeyError(f"Unsupported attribute: {attr}")

    def setxattr(self, key: str, attr: str, value: str) -> None:
        if attr not in _S3_WRITABLE:
            raise PermissionError(f"Attribute {attr} is read-only")

        full_key = self._full_key(key)  # type: ignore[attr-defined]
        bucket = self._bucket  # type: ignore[attr-defined]
        s3 = self._s3  # type: ignore[attr-defined]

        if attr == "content_type":
            s3.copy_object(
                Bucket=bucket,
                Key=full_key,
                CopySource={"Bucket": bucket, "Key": full_key},
                ContentType=value,
                MetadataDirective="REPLACE",
            )
