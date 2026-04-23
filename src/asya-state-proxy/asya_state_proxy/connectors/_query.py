"""Mango-style /query support for object-store connectors via DuckDB.

Connectors inherit ObjectStoreQueryMixin to expose query(). Each connector
backend provides _setup_duckdb_source() to wire DuckDB to its storage.

  - S3 connectors: use DuckDB httpfs (reads directly from S3, no disk copy).
  - GCS connectors (and generic fallback): download to a temp dir, read_text locally.

Install DuckDB: pip install 'asya-state-proxy[query]'
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger("asya.state-proxy")

# Guard field names against SQL injection.
_VALID_FIELD = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")

# Hard limit on list() results when using the generic (temp-file) path.
MAX_QUERY_KEYS = 10_000
# Cap fetch per call for the temp-file path only; httpfs path has no cap.
MAX_FETCH_KEYS = 1_000


@dataclass
class QueryRequest:
    prefix: str = ""
    filter: dict[str, Any] = field(default_factory=dict)
    sort: list[str] = field(default_factory=list)
    limit: int = 0
    offset: int = 0


@dataclass
class QueryResult:
    rows: list[dict[str, Any]]
    total: int


def _validate_field(name: str) -> None:
    if not _VALID_FIELD.match(name):
        raise ValueError(f"invalid field name: {name!r}")


def _build_where(filter_map: dict[str, Any]) -> tuple[str, list[Any]]:
    if not filter_map:
        return "", []
    parts = []
    params: list[Any] = []
    for field_name, value in filter_map.items():
        _validate_field(field_name)
        parts.append(f"json_extract_string(content, '$.{field_name}') = ?")
        params.append(str(value))
    return " WHERE " + " AND ".join(parts), params


def _build_order(sort_fields: list[str]) -> str:
    if not sort_fields:
        return ""
    parts = []
    for s in sort_fields:
        if s.startswith("-"):
            field_name, direction = s[1:], "DESC"
        else:
            field_name, direction = s, "ASC"
        _validate_field(field_name)
        parts.append(f"json_extract_string(content, '$.{field_name}') {direction}")
    return " ORDER BY " + ", ".join(parts)


def _safe_sql_str(value: str, name: str) -> str:
    """Verify a string is safe to embed inside a SQL single-quoted literal."""
    if "'" in value or "\n" in value or "\r" in value:
        raise ValueError(f"Unsafe {name} value — cannot embed in SQL string literal")
    return value


class ObjectStoreQueryMixin:
    """Adds query() to any StateProxyConnector implementing list() + read().

    Subclasses override _setup_duckdb_source() to provide a DuckDB source
    table (or view) named '_tmp' with columns (filename VARCHAR, content VARCHAR).

    duckdb is imported lazily — connectors that never call query() don't need it.
    """

    def query(self, req: QueryRequest) -> QueryResult:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "duckdb is required for /query — install: pip install 'asya-state-proxy[query]'"
            ) from exc

        where, params = _build_where(req.filter)
        order = _build_order(req.sort)
        limit_clause = f" LIMIT {req.limit}" if req.limit else ""
        offset_clause = f" OFFSET {req.offset}" if req.offset else ""

        with tempfile.TemporaryDirectory() as tmpdir:
            conn = duckdb.connect(":memory:")
            try:
                empty = self._setup_duckdb_source(conn, req.prefix or "", tmpdir)
                if empty:
                    return QueryResult(rows=[], total=0)

                # `where` and `order` are built from validated field names only; values
                # are passed as `params` (parameterized) — not subject to SQL injection.
                count_sql = f"SELECT COUNT(*) FROM _tmp{where}"  # nosec B608  # nosemgrep
                total_row = conn.execute(count_sql, params).fetchone()
                total = total_row[0] if total_row else 0

                data_sql = f"SELECT content FROM _tmp{where}{order}{limit_clause}{offset_clause}"  # nosec B608  # nosemgrep
                rows_raw = conn.execute(data_sql, params).fetchall()
            finally:
                conn.close()

        rows = []
        for (content,) in rows_raw:
            try:
                rows.append(json.loads(content))
            except (json.JSONDecodeError, TypeError):
                logger.warning("query: skipping non-JSON document in result set")

        logger.debug("query: total=%d returned=%d", total, len(rows))
        return QueryResult(rows=rows, total=total)

    def _setup_duckdb_source(self, conn: Any, prefix: str, tmpdir: str) -> bool:
        """Create '_tmp (filename VARCHAR, content VARCHAR)' in the DuckDB connection.

        Returns True if there are no objects to query (caller returns empty result).
        Default implementation downloads objects to tmpdir via list()+read().
        Override in S3/GCS connectors to use httpfs for streaming reads.
        """
        listed = self.list(prefix, delimiter="")  # type: ignore[attr-defined]
        keys = listed.keys
        if not keys:
            return True
        if len(keys) > MAX_QUERY_KEYS:
            raise ValueError(
                f"prefix {prefix!r} matches {len(keys)} objects; max is {MAX_QUERY_KEYS} — use a narrower prefix"
            )
        fetch_keys = keys[:MAX_FETCH_KEYS]
        logger.debug("query: listing %d keys, fetching %d via temp dir", len(keys), len(fetch_keys))

        _fetch_to_dir(self, fetch_keys, tmpdir)
        glob = os.path.join(tmpdir, "*.json")
        # glob is a local temp-dir path, not user input.
        load_sql = f"CREATE TABLE _tmp AS SELECT filename, content FROM read_text('{glob}') WHERE content IS NOT NULL"  # nosec B608  # nosemgrep
        conn.execute(load_sql)
        return False


def _fetch_to_dir(connector: Any, keys: list[str], tmpdir: str) -> None:
    """Download each key and write as <sanitized>.json in tmpdir."""
    for key in keys:
        try:
            data = connector.read(key).read()
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning("query: failed to read key=%r: %s", key, exc)
            continue
        safe_name = key.replace("/", "__").replace("\\", "__").replace("\x00", "")
        path = os.path.join(tmpdir, safe_name + ".json")
        with open(path, "w") as f:
            f.write(data.decode("utf-8", errors="replace"))


def configure_s3_httpfs(conn: Any, region: str, endpoint_url: str | None) -> None:
    """Configure DuckDB httpfs secrets for S3 access.

    Uses credential_chain for real AWS (reads env vars, IRSA, instance profile).
    Explicit credentials are used when a custom endpoint is set (LocalStack, MinIO).
    """
    conn.execute("LOAD httpfs")

    if endpoint_url:
        # Custom endpoint: strip protocol, use path-style URLs.
        ep = re.sub(r"^https?://", "", endpoint_url).rstrip("/")
        use_ssl = endpoint_url.startswith("https://")
        key_id = _safe_sql_str(os.environ.get("AWS_ACCESS_KEY_ID", ""), "AWS_ACCESS_KEY_ID")
        secret = _safe_sql_str(os.environ.get("AWS_SECRET_ACCESS_KEY", ""), "AWS_SECRET_ACCESS_KEY")
        ep_safe = _safe_sql_str(ep, "AWS_ENDPOINT_URL")
        region_safe = _safe_sql_str(region, "AWS_REGION")
        conn.execute(
            f"CREATE SECRET _s3 ("
            f"  TYPE S3,"
            f"  KEY_ID '{key_id}',"
            f"  SECRET '{secret}',"
            f"  REGION '{region_safe}',"
            f"  ENDPOINT '{ep_safe}',"
            f"  URL_STYLE 'path',"
            f"  USE_SSL {str(use_ssl).lower()}"
            f")"
        )
    else:
        # Real AWS: let credential_chain handle env vars, IRSA, instance profile.
        region_safe = _safe_sql_str(region, "AWS_REGION")
        conn.execute(f"CREATE SECRET _s3 (  TYPE S3,  PROVIDER credential_chain,  REGION '{region_safe}')")
