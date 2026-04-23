"""Mango-style /query support for object-store connectors via DuckDB.

Connectors inherit ObjectStoreQueryMixin to expose query(). Each connector
backend provides _setup_duckdb_source() to wire DuckDB to its storage.

Objects are fetched via the connector's own read() method (boto3 / GCS SDK)
and written to a local temp dir. DuckDB then reads locally — no network calls
from DuckDB, no S3-SDK compatibility concerns.

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

# Hard limit on list() results for a single query call.
MAX_QUERY_KEYS = 10_000
# Max number of objects fetched per call (first N from the listing).
MAX_FETCH_KEYS = 1_000
# Total bytes budget for the per-call temp dir. Objects that would push the
# accumulated download past this limit are skipped with a warning so a handful
# of large objects cannot fill the container's ephemeral storage.
MAX_TOTAL_FETCH_BYTES = 256 * 1024 * 1024  # 256 MiB
# Hard cap on result rows returned per call — protects against OOM.
MAX_RESULT_ROWS = 10_000


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
    """Build a parameterized DuckDB WHERE clause from a Mango filter.

    Field names are validated against _VALID_FIELD (alphanumeric/underscore/dot
    only) before inclusion in the SQL string. Filter values are always passed as
    `?` parameters — never embedded in the SQL string — so this is not injectable.
    """
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
    """Build a DuckDB ORDER BY clause from sort field names.

    Each field name is validated against _VALID_FIELD before inclusion.
    """
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
    """Verify a string is safe to embed inside a SQL single-quoted literal.

    Rejects values that contain single quotes (would close the literal),
    newlines, or carriage returns (could be used for injection via line splitting).
    """
    if "'" in value or "\n" in value or "\r" in value:
        raise ValueError(f"Unsafe {name} value — cannot embed in SQL string literal")
    return value


class ObjectStoreQueryMixin:
    """Adds query() to any StateProxyConnector implementing list() + read().

    _setup_duckdb_source() fetches objects via the connector's own read() method
    (which inherits the connector's full credential chain) and writes them to a
    local temp dir. DuckDB then scans locally — no S3/GCS SDK calls from DuckDB.

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

        # Always apply an upper bound: use the caller-supplied limit or MAX_RESULT_ROWS.
        effective_limit = req.limit if 0 < req.limit <= MAX_RESULT_ROWS else MAX_RESULT_ROWS
        limit_clause = f" LIMIT {effective_limit}"
        offset_clause = f" OFFSET {req.offset}" if req.offset else ""

        with tempfile.TemporaryDirectory() as tmpdir:
            conn = duckdb.connect(":memory:")
            try:
                empty = self._setup_duckdb_source(conn, req.prefix or "", tmpdir)
                if empty:
                    return QueryResult(rows=[], total=0)

                # Safety: field names are regex-validated; values are in `params` (parameterized).
                count_sql = f"SELECT COUNT(*) FROM _tmp{where}"  # nosec B608  # nosemgrep
                total_row = conn.execute(count_sql, params).fetchone()  # nosemgrep
                total = total_row[0] if total_row else 0

                data_sql = f"SELECT content FROM _tmp{where}{order}{limit_clause}{offset_clause}"  # nosec B608  # nosemgrep
                rows_raw = conn.execute(data_sql, params).fetchall()  # nosemgrep
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
        """Fetch objects via list()+read() into tmpdir, then load into DuckDB.

        Returns True when no objects are available (caller returns empty result).
        Subclasses may override to substitute a different fetch strategy.
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
        logger.debug("query: listing %d keys, fetching up to %d", len(keys), len(fetch_keys))

        files_written = _fetch_to_dir(self, fetch_keys, tmpdir)
        if files_written == 0:
            return True

        glob = os.path.join(tmpdir, "*.json")
        # glob is a system temp-dir path, not user input.
        load_sql = f"CREATE TABLE _tmp AS SELECT filename, content FROM read_text('{glob}') WHERE content IS NOT NULL"  # nosec B608  # nosemgrep
        conn.execute(load_sql)  # nosemgrep
        return False


def _fetch_to_dir(connector: Any, keys: list[str], tmpdir: str) -> int:
    """Download each key and write as <sanitized>.json in tmpdir.

    Stops downloading when the accumulated byte count would exceed
    MAX_TOTAL_FETCH_BYTES to protect container ephemeral storage. Returns the
    number of files successfully written.
    """
    total_bytes = 0
    files_written = 0
    for key in keys:
        try:
            data = connector.read(key).read()
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning("query: failed to read key=%r: %s", key, exc)
            continue

        total_bytes += len(data)
        safe_name = key.replace("/", "__").replace("\\", "__").replace("\x00", "")
        path = os.path.join(tmpdir, safe_name + ".json")
        with open(path, "w") as f:
            f.write(data.decode("utf-8", errors="replace"))
        files_written += 1

        if total_bytes > MAX_TOTAL_FETCH_BYTES:
            logger.warning(
                "query: stopping fetch at %d bytes (%d files) — "
                "remaining keys skipped; narrow the prefix for complete results",
                total_bytes,
                files_written,
            )
            break

    logger.debug("query: fetched %d files, %d bytes total", files_written, total_bytes)
    return files_written
