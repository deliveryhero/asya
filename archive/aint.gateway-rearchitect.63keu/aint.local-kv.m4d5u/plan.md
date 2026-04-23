# PR6: local-kv — Low-Infra Gateway State Proxy

## Goal

Build `cmd/local-kv` — a new Go binary in `asya-state-proxy-go` that
implements the full state-proxy interface (CRUD + /query) backed by local
storage. Zero external dependencies: no Postgres, no S3, no GCS.

## Modes

### mode=inmem
Pure in-memory `sync.RWMutex + map[string][]byte`. State is lost on pod
restart. Fastest possible. Suitable for CI, ephemeral dev environments.

### mode=pvc
JSON files on a local directory (e.g., `/data`), typically backed by a PVC.
State survives pod restarts. `flock` per-key for atomic WriteConditional.

**Both modes: gateway.replicaCount must be 1.** The Helm chart emits a
validation error if `backend: local-kv` and `replicaCount > 1`.

## Binary location

Sits alongside `pg-kv`, `s3-kv`, `gcs-kv` in `asya-state-proxy-go`.
Dockerfile.go builds all four binaries; Helm selects via `command: ["/local-kv"]`.

No new Docker image needed — covered by existing `asya-state-proxy-go`.

## File layout (new files only)

```
src/asya-state-proxy/go/
  cmd/local-kv/
    main.go              # entrypoint: read env, wire connector + QueryEngine
  internal/localkv/
    connector.go         # inmem + pvc backends, flock, routing
    connector_test.go    # unit tests (temp dir for pvc mode)
    query.go             # DuckDB engine reading local files directly
    query_test.go        # integration tests with real DuckDB
```

## Active/archive schema (opt-in config)

```
LOCAL_KV_BASE_DIR=/data          # storage root (pvc mode)
LOCAL_KV_PARTITION=true          # enable active/ + archive/ subdirs
LOCAL_KV_ARCHIVE_STATUSES=completed,failed,canceled,succeeded
```

When `PARTITION=false` (default): flat `{base_dir}/{key}.json`.
When `PARTITION=true`:
- active/archive routing on Write/WriteConditional based on `status` field
- `List()` only walks `active/` → FindExpired scope = current active tasks
- `flock` makes Write+Delete atomic within single process (no saga race)

## DuckDB query path

Files are already local → DuckDB reads directly, no `fetchToTempDir`:

```go
glob := filepath.Join(baseDir, "active", "*.json")  // or flat dir
// CREATE OR REPLACE TABLE _tmp AS SELECT filename, content FROM read_text(glob)
```

FindExpired latency: `os.Glob` + DuckDB in-process scan = microseconds.
No S3 GETs, no network, no API costs.

## Helm chart changes

New backend option in `asya-gateway/values.yaml`:
```yaml
stateProxy:
  mesh:
    backend: local-kv     # new option
    localKv:
      mode: pvc           # inmem | pvc
      storageDir: /data/mesh
      partition: true
      archiveStatuses: completed,failed,canceled,succeeded
```

`deployment.yaml`:
- When `backend: local-kv`: inject `command: ["/local-kv"]`, mount emptyDir
  (inmem) or PVC claim (pvc) at `storageDir`, mount emptyDir at `/tmp` (DuckDB).
- Validation: fail if `replicaCount > 1`.

## E2E changes

New profile `sqs-s3-pvc`:
- SQS transport (LocalStack)
- S3 actor/crew persistence (LocalStack)
- `backend: local-kv`, `mode: pvc`, `partition: true`
- No Postgres chart deployed → validates zero-database setup

Existing profiles renamed:
- `pubsub-gcs` → `pubsub-gcs-pg` (retains pg-kv for gateway)
- `sqs-s3`     → `sqs-s3-pg`     (retains pg-kv for gateway)

## Documented limitation

> **local-kv requires `replicaCount: 1`.** In-memory mode is non-persistent
> (state lost on restart). PVC mode survives restarts but PVCs are
> ReadWriteOnce — only one pod can mount at a time. For high-availability
> gateway deployments, use `backend: pg-kv` with a managed Postgres instance.

## Success criteria

- [ ] `go test ./internal/localkv/... -count=1` passes (inmem + pvc + DuckDB)
- [ ] `helm lint` clean with `backend: local-kv`
- [ ] sqs-s3-pvc E2E: gateway 4/4 Running, /ready OK, no Postgres pod deployed
- [ ] FindExpired latency < 10ms at 100 active tasks (vs ~500ms for s3kv)
- [ ] Helm validation error when replicaCount > 1 with local-kv backend
