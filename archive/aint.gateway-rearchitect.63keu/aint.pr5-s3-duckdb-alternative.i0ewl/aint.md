---
title: "PR5: DuckDB /query for S3/GCS Python state proxy connectors"
status: merged
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - gateway-rearchitect
  - pr:463
  - branch:gateway-rearchitect/i0ewl.py-duckdb-query
dependencies:
  - 9bb3j
---


## What shipped (PR #463)

`POST /query` on `s3-buffered-lww` and `gcs-buffered-lww` Python connectors.
Mango-style filter/sort/limit/offset over stored objects via DuckDB in-process.

### Implementation decisions

**boto3 fetch path, not httpfs.**
DuckDB's S3 httpfs reimplements SigV4 signing and has known compatibility gaps
with MinIO and LocalStack (all component tests returned 500). Using the connector's
own `list()` + `read()` (boto3 / GCS SDK) and writing to a temp dir is portable
across every S3-compatible store, relies on the existing credential chain, and
requires no extra configuration.

**Disk budget (`MAX_TOTAL_FETCH_BYTES = 256 MiB`).**
`_fetch_to_dir` stops after the file that pushes total bytes over the budget,
so a single large object is always returned but a flood cannot fill container
ephemeral storage. Configurable via `QUERY_MAX_FETCH_BYTES`.

**All limits are env-var configurable.**
`QUERY_MAX_KEYS`, `QUERY_MAX_FETCH_KEYS`, `QUERY_MAX_FETCH_BYTES`,
`QUERY_MAX_RESULT_ROWS` are read at startup via `_env_int()`. Defaults are
conservative (256 MiB, 1 000 fetched keys, 10 000 listed keys, 10 000 result rows).
Wired into the `asya-crew` Helm chart via `persistence.config.query.*`.

**HTTP server hardening.**
Body size limited to 1 MiB; `filter` and `sort` types validated before reaching
connector code; negative limit/offset rejected; `limit > MAX_RESULT_ROWS` rejected.

### Test coverage

- 203 Python unit tests (helpers, stub connector, S3 via moto, HTTP server)
- 2 precise budget tests via monkeypatch (stop-after-second, single-large-object)
- 11 component tests in `testing/component/state-proxy/tests/test_query.py`
  covering filter, prefix scope, limit, sort, validation; auto-skip on 501 connectors

### Docs and charts

- `docs/reference/state-proxy-connectors/s3.md` — `/query` section with request
  format, limit table (env vars, defaults, exceeded behaviour), Helm example
- `docs/reference/state-proxy-connectors/gcs.md` — same
- `docs/contributing/testing-state-proxy.md` — component test notes for /query
- `deploy/helm-charts/asya-crew/` — `persistence.config.query.*` values wired
  to `QUERY_MAX_*` env vars on the connector container

## History (closed PRs)

**PR #457** (closed) — asya-gateway Helm chart: configurable `stateProxy.mesh.backend`.
**PR #458** (closed) — s3kv + gcskv Go connectors (S3/GCS+DuckDB). Included multiple
DuckDB stability fixes (read_text vs read_json_auto, context isolation, maxFetchKeys).
Both closed in favour of a clean rebase; the Go connector work is preserved in the
old branch `gateway-rearchitect/i0ewl.s3-kv-duckdb`.
