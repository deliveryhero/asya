# Design: GCS Bucket Connectors (CAS + LWW)

## Summary

Add two new `asya-state-proxy` connectors for Google Cloud Storage:

| Connector | Module | Semantics |
|-----------|--------|-----------|
| `gcs-buffered-lww` | `asya_state_proxy.connectors.gcs_buffered_lww` | Last-write-wins, buffered |
| `gcs-buffered-cas` | `asya_state_proxy.connectors.gcs_buffered_cas` | Compare-and-swap via GCS generations, buffered |

Both follow the exact same `StateProxyConnector` interface and directory layout as
the existing S3 connectors. The only differences are the storage SDK
(`google-cloud-storage` vs `boto3`) and the CAS primitive (GCS generation numbers
vs S3 ETags).

---

## Motivation

S3-compatible storage is not always available or desirable. GCS is the native
object store on GKE and Google Cloud. Teams running Asya on GKE should be able to
use GCS buckets for actor state without routing through an S3-compatibility layer
(which adds latency, operational surface, and credential complexity).

---

## GCS Concepts Mapping

| S3 Concept | GCS Equivalent | Notes |
|------------|----------------|-------|
| Bucket | Bucket | Same semantics |
| Key | Blob name | Forward-slash delimited, same as S3 |
| ETag (content hash) | `generation` (int64) | Monotonically increasing per-object. Set by GCS on every mutation. |
| `IfMatch` (conditional put) | `if_generation_match` | Precondition on `upload_from_file()`, `delete()`, etc. |
| `PreconditionFailed` (botocore ClientError) | `google.api_core.exceptions.PreconditionFailed` | HTTP 412, typed exception |
| `put_object()` | `blob.upload_from_file()` | Buffered upload from file-like object |
| `get_object()` | `blob.download_as_bytes()` | Returns bytes directly (no streaming body wrapper needed for buffered mode) |
| `head_object()` | `blob.reload()` | Fetches metadata (size, content_type, generation) without downloading body |
| `list_objects_v2()` | `client.list_blobs(prefix=, delimiter=)` | Returns `Blob` iterator + `prefixes` attribute |
| `delete_object()` | `blob.delete()` | Silent on missing (same as S3) |
| `generate_presigned_url()` | `blob.generate_signed_url()` | Requires service account key or IAM signBlob permission |
| `copy_object()` with metadata replace | `blob.content_type = ...; blob.patch()` | Simpler than S3 copy-to-self |
| `ContentLength` | `blob.size` | From metadata reload |
| `StorageClass` | `blob.storage_class` | Same concept |
| `VersionId` | `blob.generation` | Integer, not string |

---

## Architecture

### New Files

```
src/asya-state-proxy/
├── asya_state_proxy/connectors/
│   ├── _gcs_xattr.py                    # Shared xattr mixin (mirrors _s3_xattr.py)
│   ├── gcs_buffered_lww/
│   │   ├── __init__.py
│   │   ├── __main__.py                  # Entry point
│   │   └── connector.py                 # GCSBufferedLWW
│   └── gcs_buffered_cas/
│       ├── __init__.py
│       ├── __main__.py                  # Entry point
│       └── connector.py                 # GCSBufferedCAS
├── tests/
│   ├── test_gcs_buffered_lww.py
│   └── test_gcs_buffered_cas.py
├── Dockerfile.gcs-buffered-lww
└── Dockerfile.gcs-buffered-cas
```

### Unchanged Files

- `interface.py` — no changes, connectors implement existing ABC
- `server.py` — no changes, serves any `StateProxyConnector`
- `_s3_xattr.py` — untouched, only used by S3 connectors

### Modified Files

- `pyproject.toml` — add `gcs` optional dependency group
- `Makefile` — add `--extra gcs` to test command
- `testing/component/state-proxy/` — add `gcs-lww` and `gcs-cas` profiles

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `STATE_BUCKET` | Yes | — | GCS bucket name |
| `STATE_PREFIX` | No | `""` | Key prefix within the bucket |
| `GCS_PROJECT` | No | SDK default | GCP project ID (usually auto-detected from credentials) |
| `STORAGE_EMULATOR_HOST` | No | — | Override for fake-gcs-server in testing (e.g., `http://fake-gcs:4443`) |
| `STATE_PRESIGN_TTL` | No | `3600` | Signed URL expiry in seconds |
| `GOOGLE_APPLICATION_CREDENTIALS` | Prod | — | Path to service account JSON key (or use Workload Identity) |

**Credential strategy**: In production on GKE, prefer **Workload Identity** (no
static keys). The `google-cloud-storage` SDK auto-discovers credentials via
Application Default Credentials (ADC). For local/test, set
`GOOGLE_APPLICATION_CREDENTIALS` or `STORAGE_EMULATOR_HOST`.

---

## Connector Implementations

### GCSBufferedLWW

```python
"""GCS buffered last-write-wins connector.

Reads configuration from environment variables:
    STATE_BUCKET            - GCS bucket name (required)
    STATE_PREFIX            - Key prefix inside the bucket (optional, default "")
    GCS_PROJECT             - GCP project ID (optional, auto-detected)
    STORAGE_EMULATOR_HOST   - Emulator endpoint for testing (optional)
"""

import io
import logging
import os
from typing import BinaryIO

from google.cloud import storage
from google.api_core.exceptions import NotFound

from asya_state_proxy.connectors._gcs_xattr import GCSXattrMixin
from asya_state_proxy.interface import KeyMeta, ListResult, StateProxyConnector

logger = logging.getLogger("asya.state-proxy")


class GCSBufferedLWW(GCSXattrMixin, StateProxyConnector):
    """Last-write-wins GCS connector. Full body is buffered in memory."""

    def __init__(self) -> None:
        bucket_name = os.environ.get("STATE_BUCKET")
        if not bucket_name:
            raise RuntimeError("STATE_BUCKET environment variable is required")

        self._prefix = os.environ.get("STATE_PREFIX", "")
        project = os.environ.get("GCS_PROJECT")

        client = storage.Client(project=project)
        self._bucket = client.bucket(bucket_name)
        self._client = client
        self._bucket_name = bucket_name
        logger.info(
            "GCSBufferedLWW connector initialised: bucket=%s prefix=%r project=%s",
            bucket_name, self._prefix, project or "(default)",
        )

    def _full_key(self, key: str) -> str:
        if self._prefix:
            return f"{self._prefix}/{key}"
        return key

    def _strip_prefix(self, full_key: str) -> str:
        if self._prefix and full_key.startswith(self._prefix + "/"):
            return full_key[len(self._prefix) + 1 :]
        return full_key

    def read(self, key: str) -> BinaryIO:
        blob = self._bucket.blob(self._full_key(key))
        try:
            data = blob.download_as_bytes()
        except NotFound:
            raise FileNotFoundError(f"Key not found: {key}")
        logger.debug("read key=%s size=%d", key, len(data))
        return io.BytesIO(data)

    def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
        blob = self._bucket.blob(self._full_key(key))
        body = data.read()
        blob.upload_from_file(io.BytesIO(body), size=len(body), rewind=True)
        logger.debug("write key=%s size=%d", key, len(body))

    def exists(self, key: str) -> bool:
        return self._bucket.blob(self._full_key(key)).exists()

    def stat(self, key: str) -> KeyMeta | None:
        blob = self._bucket.blob(self._full_key(key))
        try:
            blob.reload()
        except NotFound:
            return None
        logger.debug("stat key=%s size=%d", key, blob.size)
        return KeyMeta(size=blob.size or 0, is_file=True)

    def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
        full_prefix = (
            self._full_key(key_prefix)
            if key_prefix
            else (self._prefix + "/" if self._prefix else "")
        )
        kwargs = {"prefix": full_prefix}
        if delimiter:
            kwargs["delimiter"] = delimiter

        iterator = self._client.list_blobs(self._bucket_name, **kwargs)
        keys = [self._strip_prefix(blob.name) for blob in iterator]
        prefixes = [self._strip_prefix(p) for p in iterator.prefixes]

        logger.debug("list prefix=%r keys=%d prefixes=%d", key_prefix, len(keys), len(prefixes))
        return ListResult(keys=keys, prefixes=prefixes)

    def delete(self, key: str) -> None:
        blob = self._bucket.blob(self._full_key(key))
        if not blob.exists():
            raise FileNotFoundError(f"Key not found: {key}")
        blob.delete()
        logger.debug("delete key=%s", key)
```

**Design notes**:
- `download_as_bytes()` returns `bytes` directly — no streaming body wrapper needed
  (unlike boto3 where `response["Body"]` is a streaming object).
- `upload_from_file()` takes a file-like object. We wrap `body` in `BytesIO` because
  we've already consumed the input stream.
- `list_blobs()` returns an iterator whose `.prefixes` attribute is populated after
  iteration — we must consume the iterator before accessing prefixes.
- `blob.exists()` / `blob.reload()` are metadata-only RPCs (no body download).

### GCSBufferedCAS

The CAS connector extends the LWW pattern with **generation-based optimistic locking**:

```python
"""GCS buffered compare-and-swap connector.

Uses GCS object generation numbers for optimistic concurrency control.
On read(), caches the generation. On write(), passes if_generation_match
to enforce the cached generation. If the object was modified between
read and write, GCS returns 412 Precondition Failed.
"""

import io
import logging
import os
from typing import BinaryIO

from google.cloud import storage
from google.api_core.exceptions import NotFound, PreconditionFailed

from asya_state_proxy.connectors._gcs_xattr import GCSXattrMixin
from asya_state_proxy.interface import KeyMeta, ListResult, StateProxyConnector

logger = logging.getLogger("asya.state-proxy")


class GCSBufferedCAS(GCSXattrMixin, StateProxyConnector):
    """Compare-and-swap GCS connector using generation-based preconditions.

    Maintains an in-memory generation cache to detect concurrent modifications.
    When writing a key that was previously read, the write is conditional
    on the cached generation matching the current GCS generation. If the object
    was modified externally, the write raises FileExistsError.
    """

    def __init__(self) -> None:
        bucket_name = os.environ.get("STATE_BUCKET")
        if not bucket_name:
            raise RuntimeError("STATE_BUCKET environment variable is required")

        self._prefix = os.environ.get("STATE_PREFIX", "")
        project = os.environ.get("GCS_PROJECT")

        client = storage.Client(project=project)
        self._bucket = client.bucket(bucket_name)
        self._client = client
        self._bucket_name = bucket_name
        self._generations: dict[str, int] = {}
        logger.info(
            "GCSBufferedCAS connector initialised: bucket=%s prefix=%r project=%s",
            bucket_name, self._prefix, project or "(default)",
        )

    def _full_key(self, key: str) -> str:
        if self._prefix:
            return f"{self._prefix}/{key}"
        return key

    def _strip_prefix(self, full_key: str) -> str:
        if self._prefix and full_key.startswith(self._prefix + "/"):
            return full_key[len(self._prefix) + 1 :]
        return full_key

    def read(self, key: str) -> BinaryIO:
        blob = self._bucket.blob(self._full_key(key))
        try:
            data = blob.download_as_bytes()
        except NotFound:
            raise FileNotFoundError(f"Key not found: {key}")
        # After download, blob.generation is populated from the response
        self._generations[key] = blob.generation
        logger.debug("read key=%s size=%d generation=%d", key, len(data), blob.generation)
        return io.BytesIO(data)

    def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
        blob = self._bucket.blob(self._full_key(key))
        body = data.read()

        # Build precondition kwargs
        upload_kwargs: dict = {"size": len(body), "rewind": True}
        cached_gen = self._generations.get(key)
        if cached_gen is not None:
            upload_kwargs["if_generation_match"] = cached_gen

        try:
            blob.upload_from_file(io.BytesIO(body), **upload_kwargs)
        except PreconditionFailed:
            raise FileExistsError(
                f"CAS conflict: key={key} cached_generation={cached_gen}"
            )

        # After upload, blob.generation is updated to the new generation
        blob.reload()
        self._generations[key] = blob.generation
        logger.debug("write key=%s size=%d generation=%d", key, len(body), blob.generation)

    def exists(self, key: str) -> bool:
        return self._bucket.blob(self._full_key(key)).exists()

    def stat(self, key: str) -> KeyMeta | None:
        blob = self._bucket.blob(self._full_key(key))
        try:
            blob.reload()
        except NotFound:
            return None
        logger.debug("stat key=%s size=%d", key, blob.size)
        return KeyMeta(size=blob.size or 0, is_file=True)

    def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
        full_prefix = (
            self._full_key(key_prefix)
            if key_prefix
            else (self._prefix + "/" if self._prefix else "")
        )
        kwargs = {"prefix": full_prefix}
        if delimiter:
            kwargs["delimiter"] = delimiter

        iterator = self._client.list_blobs(self._bucket_name, **kwargs)
        keys = [self._strip_prefix(blob.name) for blob in iterator]
        prefixes = [self._strip_prefix(p) for p in iterator.prefixes]

        logger.debug("list prefix=%r keys=%d prefixes=%d", key_prefix, len(keys), len(prefixes))
        return ListResult(keys=keys, prefixes=prefixes)

    def getxattr(self, key: str, attr: str) -> str:
        """Override to return cached generation when available."""
        if attr == "generation" and key in self._generations:
            return str(self._generations[key])
        return super().getxattr(key, attr)

    def delete(self, key: str) -> None:
        blob = self._bucket.blob(self._full_key(key))
        if not blob.exists():
            raise FileNotFoundError(f"Key not found: {key}")
        blob.delete()
        self._generations.pop(key, None)
        logger.debug("delete key=%s", key)
```

**CAS mechanism details**:

1. **`read()`**: Downloads object, caches `blob.generation` (an int64 that GCS
   increments on every mutation).
2. **`write()` with cached generation**: Passes `if_generation_match=cached_gen` to
   `upload_from_file()`. If object was modified since the read, GCS returns HTTP 412
   (`PreconditionFailed`), which we map to `FileExistsError`.
3. **`write()` without cached generation** (new key): No precondition — unconditional
   write (same as LWW).
4. **Post-write update**: After successful write, `blob.reload()` fetches the new
   generation, updating the cache for subsequent writes.
5. **`delete()`**: Clears the generation cache entry.

**Why `blob.reload()` after write?**
`upload_from_file()` in the `google-cloud-storage` SDK does not always populate
`blob.generation` on the local object after upload (depends on SDK version and
response parsing). Calling `blob.reload()` is a single metadata HEAD request that
guarantees we have the new generation for subsequent CAS writes.

---

## GCS xattr Mixin

```python
"""Shared xattr implementation for GCS-based connectors.

Mirrors _s3_xattr.py. Subclasses must provide:
    self._bucket (google.cloud.storage.Bucket)
    self._bucket_name (str)
    self._full_key(key) -> str
"""

import os

from google.api_core.exceptions import NotFound


_GCS_ATTRS = [
    "url",
    "signed_url",
    "generation",
    "content_type",
    "storage_class",
    "metageneration",
]
_GCS_WRITABLE = {"content_type"}


class GCSXattrMixin:
    """Mixin that adds xattr support for GCS-backed connectors."""

    def listxattr(self, key: str) -> list[str]:
        return list(_GCS_ATTRS)

    def getxattr(self, key: str, attr: str) -> str:
        full_key = self._full_key(key)
        bucket = self._bucket
        bucket_name = self._bucket_name

        if attr == "url":
            return f"gs://{bucket_name}/{full_key}"

        if attr == "signed_url":
            ttl = int(os.environ.get("STATE_PRESIGN_TTL", "3600"))
            blob = bucket.blob(full_key)
            return blob.generate_signed_url(expiration=ttl, method="GET")

        if attr in ("generation", "content_type", "storage_class", "metageneration"):
            blob = bucket.blob(full_key)
            try:
                blob.reload()
            except NotFound:
                raise FileNotFoundError(f"Key not found: {key}")
            if attr == "generation":
                return str(blob.generation)
            if attr == "content_type":
                return blob.content_type or "application/octet-stream"
            if attr == "metageneration":
                return str(blob.metageneration)
            # storage_class
            return blob.storage_class or "STANDARD"

        raise KeyError(f"Unsupported attribute: {attr}")

    def setxattr(self, key: str, attr: str, value: str) -> None:
        if attr not in _GCS_WRITABLE:
            raise PermissionError(f"Attribute {attr} is read-only")

        full_key = self._full_key(key)
        blob = self._bucket.blob(full_key)

        if attr == "content_type":
            blob.content_type = value
            blob.patch()
```

**Attribute comparison with S3**:

| S3 Attribute | GCS Attribute | Notes |
|-------------|---------------|-------|
| `url` → `s3://bucket/key` | `url` → `gs://bucket/key` | URI scheme difference |
| `presigned_url` | `signed_url` | GCS naming convention |
| `etag` | `generation` | Different primitive: hash vs counter |
| `content_type` | `content_type` | Same (read/write) |
| `version` | `metageneration` | GCS metadata version counter |
| `storage_class` | `storage_class` | Same concept |

**Signed URL caveat**: `blob.generate_signed_url()` requires either:
- A service account JSON key file (specified via `GOOGLE_APPLICATION_CREDENTIALS`), or
- IAM `signBlob` permission with Workload Identity.

On GKE with Workload Identity, the recommended approach is to grant
`roles/iam.serviceAccountTokenCreator` to the pod's KSA. If neither is
available, `getxattr("signed_url")` will raise an error at runtime — this is
acceptable because signed URLs are optional metadata, not core CRUD.

---

## Dependency Management

### pyproject.toml changes

```toml
[project.optional-dependencies]
s3 = ["boto3>=1.35"]
gcs = ["google-cloud-storage>=2.14"]
redis = ["redis>=5.0"]
test = [
    "pytest>=8.0",
    "moto[s3]>=5.0",
    "fakeredis>=2.21",
    "gcsfs>=2024.2",          # for mock GCS in tests (optional, see Testing)
]
```

### Makefile changes

```makefile
test-unit:
	uv run --project . --extra test --extra s3 --extra redis --extra gcs pytest tests/ -v
```

---

## Dockerfiles

### Dockerfile.gcs-buffered-lww

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
COPY asya_state_proxy/ asya_state_proxy/
RUN pip install --no-cache-dir ".[gcs]"
ENTRYPOINT ["python", "-m", "asya_state_proxy.connectors.gcs_buffered_lww"]
```

### Dockerfile.gcs-buffered-cas

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
COPY asya_state_proxy/ asya_state_proxy/
RUN pip install --no-cache-dir ".[gcs]"
ENTRYPOINT ["python", "-m", "asya_state_proxy.connectors.gcs_buffered_cas"]
```

**Image naming** (matches existing convention):
- `ghcr.io/deliveryhero/asya-state-proxy-gcs-buffered-lww:v1.0.0`
- `ghcr.io/deliveryhero/asya-state-proxy-gcs-buffered-cas:v1.0.0`

---

## Testing Strategy

### Unit Tests (mocked)

**Mock approach**: Use `unittest.mock.patch` on `google.cloud.storage.Client`. The
`google-cloud-storage` SDK does not have a `moto`-equivalent mock library with the
same maturity. Options considered:

| Option | Verdict |
|--------|---------|
| `gcsfs` + `fsspec` memory filesystem | Too high-level, doesn't mock blob API 1:1 |
| `fake-gcs-server` (Docker) | Good for component tests, too heavy for unit tests |
| `unittest.mock` on `storage.Client` | Lightweight, matches existing `moto` pattern in spirit |
| `google-cloud-testutils` | Internal Google package, not well-maintained |

**Decision**: Use `unittest.mock` for unit tests. This mirrors the approach taken in
the CAS conflict test for S3 (where `moto` doesn't enforce `IfMatch` preconditions
and the test patches `put_object` directly).

For GCS CAS specifically, we'll mock `upload_from_file` to raise
`PreconditionFailed` when `if_generation_match` is present and stale — exactly
paralleling the S3 CAS test's `mock_put` pattern.

**Test files**:
- `tests/test_gcs_buffered_lww.py` — mirrors `test_s3_buffered_lww.py` structure
- `tests/test_gcs_buffered_cas.py` — mirrors `test_s3_buffered_cas.py` structure

**Test coverage parity**: Every test case in the S3 suites should have a GCS
equivalent:

| Test | LWW | CAS |
|------|-----|-----|
| write_then_read_returns_same_data | Yes | Yes |
| read_missing_key_raises_file_not_found | Yes | Yes |
| exists_returns_true_after_write | Yes | Yes |
| stat_returns_key_meta_with_correct_size | Yes | Yes |
| list_returns_keys_under_prefix | Yes | Yes |
| list_with_delimiter_returns_prefixes | Yes | Yes |
| delete_existing_key | Yes | Yes |
| delete_missing_key_raises_file_not_found | Yes | Yes |
| write_overwrites_existing_key_lww | Yes | — |
| state_prefix_is_applied | Yes | Yes |
| listxattr_returns_gcs_attrs | Yes | Yes |
| getxattr_url_returns_gs_uri | Yes | Yes |
| write_new_key_without_read_succeeds | — | Yes |
| write_after_read_with_no_intervening_change | — | Yes |
| write_after_external_change_raises_conflict | — | Yes |
| delete_clears_generation_cache | — | Yes |
| getxattr_generation_uses_cached_value | — | Yes |

### Component Tests (Docker Compose with fake-gcs-server)

Add two new profiles to `testing/component/state-proxy/`:

**`profiles/gcs-lww.yml`**:
```yaml
include:
- path: ../../../shared/compose/fake-gcs.yml    # New shared service

services:
  state-proxy-connector:
    extends:
      file: ../compose/state-actors.yml
      service: state-proxy-connector
    depends_on:
      storage-setup:
        condition: service_completed_successfully

  asya-state-ops-runtime:
    extends:
      file: ../compose/state-actors.yml
      service: asya-state-ops-runtime

  tester:
    extends:
      file: ../compose/tester.yml
      service: tester
    depends_on:
      asya-state-ops-runtime:
        condition: service_healthy

volumes:
  state-sockets:
  runtime-sockets:
```

**`profiles/.env.gcs-lww`**:
```
CONNECTOR_DOCKERFILE=Dockerfile.gcs-buffered-lww
WRITE_MODE=buffered
STATE_BUCKET=asya-state-test
STORAGE_EMULATOR_HOST=http://fake-gcs:4443
```

**`profiles/.env.gcs-cas`**: Same, with `Dockerfile.gcs-buffered-cas`.

**New shared compose service** (`testing/shared/compose/fake-gcs.yml`):
```yaml
services:
  fake-gcs:
    image: fsouza/fake-gcs-server:latest
    command: ["-scheme", "http", "-port", "4443"]
    ports:
      - "4443"
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:4443/storage/v1/b"]
      interval: 2s
      timeout: 5s
      retries: 5

  storage-setup:
    image: curlimages/curl:latest
    depends_on:
      fake-gcs:
        condition: service_healthy
    entrypoint: >
      sh -c "curl -s -X POST
      'http://fake-gcs:4443/storage/v1/b?project=test'
      -H 'Content-Type: application/json'
      -d '{\"name\": \"asya-state-test\"}'"
```

**Makefile update** — add GCS profiles to `test` target:
```makefile
test: clean
	$(MAKE) test-one CONNECTOR_PROFILE=s3-lww
	$(MAKE) test-one CONNECTOR_PROFILE=s3-passthrough
	$(MAKE) test-one CONNECTOR_PROFILE=s3-cas
	$(MAKE) test-one CONNECTOR_PROFILE=redis-cas
	$(MAKE) test-one CONNECTOR_PROFILE=gcs-lww
	$(MAKE) test-one CONNECTOR_PROFILE=gcs-cas
```

### fake-gcs-server

[fsouza/fake-gcs-server](https://github.com/fsouza/fake-gcs-server) is a mature,
widely-used GCS emulator that supports:
- Object CRUD (upload, download, delete, list)
- Generation numbers and preconditions (`if_generation_match`)
- Signed URLs (limited, sufficient for testing)
- JSON API and XML API

The `google-cloud-storage` Python SDK supports `STORAGE_EMULATOR_HOST` natively —
when set, the client routes all requests to the emulator with no code changes.

---

## Injector Integration

The existing `asya-injector` code at `src/asya-injector/internal/injection/state_proxy.go`
already handles state proxy injection generically. No injector changes are needed:

- The injector reads `spec.stateProxy[].connector.image` and creates a sidecar
  container with that image.
- Environment variables from `spec.stateProxy[].connector.env` are passed through.
- Write mode is inferred from the image name (contains "passthrough" → passthrough,
  otherwise → buffered). Both GCS connectors are buffered, so this works.

**Verification**: The image name `asya-state-proxy-gcs-buffered-lww` does not contain
"passthrough", so `inferWriteMode()` correctly returns `"buffered"`.

---

## AsyncActor CRD Example

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: context-store
spec:
  actor: context-store
  transport: sqs
  stateProxy:
    - name: context
      mount:
        path: /state/context
      writeMode: buffered
      connector:
        image: ghcr.io/deliveryhero/asya-state-proxy-gcs-buffered-cas:v1.0.0
        env:
          - name: STATE_BUCKET
            value: my-agent-contexts
          - name: STATE_PREFIX
            value: conversations
          # On GKE with Workload Identity: no explicit credentials needed
          # On non-GKE: mount service account key and set:
          # - name: GOOGLE_APPLICATION_CREDENTIALS
          #   value: /var/run/secrets/gcp/key.json
```

---

## Implementation Plan

### Phase 1: Core connectors (this task)

1. Create `_gcs_xattr.py` mixin
2. Create `gcs_buffered_lww/` module (connector, `__init__`, `__main__`)
3. Create `gcs_buffered_cas/` module (connector, `__init__`, `__main__`)
4. Add unit tests for both connectors
5. Add `gcs` dependency group to `pyproject.toml`
6. Add Dockerfiles
7. Update Makefile

### Phase 2: Component tests

8. Create `testing/shared/compose/fake-gcs.yml`
9. Add `gcs-lww` and `gcs-cas` profiles to component tests
10. Update component test Makefile

### Phase 3: Documentation

11. Update `docs/architecture/asya-state-proxy.md` with GCS connector docs

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `blob.generation` not populated after `download_as_bytes()` | CAS broken | Verified in SDK source: `download_as_bytes()` triggers a GET that populates `generation` from response headers |
| `generate_signed_url()` fails without SA key | `getxattr("signed_url")` errors | Acceptable: signed URLs are optional metadata. Document the IAM requirement. |
| `fake-gcs-server` doesn't enforce `if_generation_match` | CAS component tests don't test real conflicts | Use mock-based unit tests for CAS semantics (same approach as S3 with moto). Verify with real GCS in CI if needed. |
| `google-cloud-storage` SDK size (~50MB with grpc) | Larger Docker images | Use `google-cloud-storage` without grpc extras. The REST transport is sufficient and much smaller. Pin `google-cloud-storage[requests]` if needed. |

---

## Out of Scope

- **GCS passthrough connector** (`gcs-passthrough`): Can be added later following
  the `s3_passthrough` pattern with `blob.download_to_file()` for streaming reads
  and resumable uploads for streaming writes.
- **Dual-region / turbo replication**: No special handling needed — these are bucket
  configuration features transparent to the connector.
- **Customer-Managed Encryption Keys (CMEK)**: Handled at the GCS bucket level, not
  at the connector level.
- **Object versioning**: GCS versioning is a bucket-level setting. The connector uses
  generations for CAS regardless of whether versioning is enabled.
