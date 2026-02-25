
★ Insight ─────────────────────────────────────
The RFC's 5-phase structure maps naturally to a dependency graph where Phase 1 (interface + framework) is the critical path — everything downstream depends on it. Phases 2 and 3 can proceed in
parallel once Phase 1's interface is defined. Phase 4 connectors only need the base framework. Phase 5 testing integrates everything. Tasks with dependencies were automatically marked as
"slopped" by git-aint (blocked by unresolved deps).
─────────────────────────────────────────────────

---
Epic 1dmf: Stateful Actors — 18 Tasks

Phase 1: Connector Interface & Framework (P1, 4 tasks)

┌─────────────┬──────────────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────┐
│     Ref     │                         Task                         │                                          Key Details                                          │
├─────────────┼──────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1ipgpc │ Define StateProxyConnector interface + HTTP protocol │ ABC with 6 methods, HTTP endpoint mappings, error response format. Foundation for everything. │
├─────────────┼──────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1iph0b │ Build connector base framework                       │ HTTP server on Unix socket, health checks, shutdown, Dockerfile base. Depends on ↑            │
├─────────────┼──────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1ipbaz │ Implement s3-buffered-lww                            │ First connector (simplest, no CAS). Reference implementation.                                 │
├─────────────┼──────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1ig161 │ Implement redis-buffered-cas                         │ CAS with WATCH/MULTI/EXEC, internal retry loop.                                               │
└─────────────┴──────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────┘

Phase 2: Runtime Interception (P1-P2, 4 tasks)

┌─────────────┬───────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────┐
│     Ref     │                       Task                        │                                   Key Details                                   │
├─────────────┼───────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1i8cbz │ Mount parser + Unix socket client + error mapping │ Env var parser, _UnixHTTPConnection, _raise_for_status. ~25 lines.              │
├─────────────┼───────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1iu28h │ Read/write file wrappers                          │ _StateFile, _BufferedWriteFile, _PassthroughWriteFile. ~40 lines.               │
├─────────────┼───────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1id0b6 │ Mount resolution + builtins patching              │ Patches builtins.open, os.stat, os.listdir, os.scandir, os.unlink, os.makedirs. │
├─────────────┼───────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1ixhrh │ Unit tests for interception layer                 │ Parser, path resolution, wrappers, error mapping, patching, local dev parity.   │
└─────────────┴───────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────┘

Phase 3: Injector & XRD Integration (P1-P2, 3 tasks)

┌─────────────┬─────────────────────────────┬──────────────────────────────────────────────────────────────────────────────────────┐
│     Ref     │            Task             │                                     Key Details                                      │
├─────────────┼─────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1i7xug │ XRD: stateProxy field       │ Optional array with name, mount.path, connector.image/env/resources.                 │
├─────────────┼─────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1i0v1k │ Injector: sidecar injection │ Inject asya-state-proxy-{name} containers, volumes, ASYA_STATE_PROXY_MOUNTS env var. │
├─────────────┼─────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1i72to │ Crossplane compositions     │ Propagate stateProxy spec through composition pipeline.                              │
└─────────────┴─────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────────┘

Phase 4: Additional Connectors (P2, 3 tasks)

┌─────────────┬──────────────────────┬──────────────────────────────────────────────────────────────────────┐
│     Ref     │         Task         │                             Key Details                              │
├─────────────┼──────────────────────┼──────────────────────────────────────────────────────────────────────┤
│ 1dmf/1i4f4u │ s3-passthrough       │ Streaming reads (chunked), multipart upload writes. For large files. │
├─────────────┼──────────────────────┼──────────────────────────────────────────────────────────────────────┤
│ 1dmf/1i58js │ s3-buffered-cas      │ S3 with ETag-based conditional PutObject for CAS.                    │
├─────────────┼──────────────────────┼──────────────────────────────────────────────────────────────────────┤
│ 1dmf/1ip8hg │ nats-kv-buffered-cas │ NATS KV with native revision-based CAS.                              │
└─────────────┴──────────────────────┴──────────────────────────────────────────────────────────────────────┘

Phase 5: Testing (P2, 4 tasks)

┌─────────────┬──────────────────────────────────────┬──────────────────────────────────────────────────────────────────────────┐
│     Ref     │                 Task                 │                               Key Details                                │
├─────────────┼──────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1ihv8x │ Component tests: runtime ↔ connector │ Docker Compose, MinIO, verify all file ops over Unix socket.             │
├─────────────┼──────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1i63ez │ Integration tests: full pipeline     │ Multi-actor pipeline with state, cross-message persistence, multi-mount. │
├─────────────┼──────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1incm3 │ CAS conflict handling tests          │ Two-layer retry strategy, concurrent writers, eventual convergence.      │
├─────────────┼──────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤
│ 1dmf/1i2v6d │ Passthrough streaming tests          │ Large file streaming, memory bounds, non-seekable verification.          │
└─────────────┴──────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────┘

---
Dependency Graph (Execution Order)

Phase 1 (interface)  ──┬──> Phase 1 (framework) ──┬──> Phase 1 (s3-lww, redis-cas)
                        │                           └──> Phase 4 (additional connectors)
                        ├──> Phase 2 (runtime)  ──────> Phase 2 (unit tests)
                        └──> Phase 3 (XRD + injector + compositions)
                                                    ↓
                                            Phase 5 (testing)

Phases 2 and 3 can run in parallel once the interface (1dmf/1ipgpc) is defined — they're independent tracks (Python runtime vs. Go injector/Helm).
