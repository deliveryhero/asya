"""Redis buffered CAS connector.

Reads configuration from environment variables:
    REDIS_URL     - Redis connection URL (required), e.g. redis://localhost:6379/0
    STATE_PREFIX  - Key prefix inside Redis (optional, default "")
"""

import io
import logging
import os
from typing import BinaryIO

import redis  # type: ignore[import-untyped]

from asya_state_proxy.interface import KeyMeta, ListResult, StateProxyConnector


logger = logging.getLogger("asya.state-proxy")


class RedisBufferedCAS(StateProxyConnector):
    """Compare-and-swap Redis connector. Full body is buffered in memory."""

    def __init__(self) -> None:
        url = os.environ.get("REDIS_URL")
        if not url:
            raise RuntimeError("REDIS_URL environment variable is required")

        self._prefix = os.environ.get("STATE_PREFIX", "")
        self._redis = redis.Redis.from_url(url)
        logger.info(
            "RedisBufferedCAS connector initialised: url=%s prefix=%r",
            url,
            self._prefix,
        )

    def _full_key(self, key: str) -> str:
        if self._prefix:
            return f"{self._prefix}:{key}"
        return key

    def _strip_prefix(self, full_key: str) -> str:
        """Remove the state prefix from a full Redis key."""
        if self._prefix and full_key.startswith(self._prefix + ":"):
            return full_key[len(self._prefix) + 1 :]
        return full_key

    def read(self, key: str) -> BinaryIO:
        """Fetch value from Redis and return as in-memory stream."""
        data = self._redis.get(self._full_key(key))
        if data is None:
            raise FileNotFoundError(f"Key not found: {key}")
        logger.debug("read key=%s size=%d", key, len(data))
        return io.BytesIO(data)

    def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
        """Write value to Redis using WATCH/MULTI/EXEC for CAS semantics."""
        full_key = self._full_key(key)
        body = data.read()
        with self._redis.pipeline() as pipe:
            try:
                pipe.watch(full_key)
                pipe.multi()
                pipe.set(full_key, body)
                pipe.execute()
            except redis.WatchError:
                raise FileExistsError(f"CAS conflict: key {key} was modified concurrently") from None
        logger.debug("write key=%s size=%d", key, len(body))

    def exists(self, key: str) -> bool:
        """Return True if the key exists in Redis."""
        return bool(self._redis.exists(self._full_key(key)))

    def stat(self, key: str) -> KeyMeta | None:
        """Return KeyMeta for the key, or None if it does not exist."""
        full_key = self._full_key(key)
        size = self._redis.strlen(full_key)
        if size == 0 and not self._redis.exists(full_key):
            return None
        logger.debug("stat key=%s size=%d", key, size)
        return KeyMeta(size=size, is_file=True)

    def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
        """List keys under the given prefix using SCAN."""
        full_prefix = self._full_key(key_prefix)
        pattern = f"{full_prefix}*"
        keys: list[str] = []
        prefixes_set: set[str] = set()

        for full_key in self._redis.scan_iter(match=pattern):
            stripped = self._strip_prefix(full_key.decode() if isinstance(full_key, bytes) else full_key)
            if delimiter and delimiter in stripped[len(key_prefix) :]:
                rest = stripped[len(key_prefix) :]
                prefix_end = rest.index(delimiter) + len(delimiter)
                prefixes_set.add(stripped[: len(key_prefix) + prefix_end])
            else:
                keys.append(stripped)

        logger.debug("list prefix=%r keys=%d prefixes=%d", key_prefix, len(keys), len(prefixes_set))
        return ListResult(keys=sorted(keys), prefixes=sorted(prefixes_set))

    def delete(self, key: str) -> None:
        """Delete key from Redis. Raises FileNotFoundError if it does not exist."""
        full_key = self._full_key(key)
        deleted = self._redis.delete(full_key)
        if deleted == 0:
            raise FileNotFoundError(f"Key not found: {key}")
        logger.debug("delete key=%s", key)
