# Notes for Future Local Testing RFC

Collected design inputs to consider when writing the local-testing RFC.

---

## Runtime HTTP Protocol Enables Direct Handler Testing

The sidecar-runtime protocol was redesigned from binary framing to HTTP
(`POST /invoke` over Unix socket). See
`.aint/aints/.closed/redesign-protocol-sidecar-runtime/rfc.md`.

The runtime can trivially switch from Unix socket to TCP for local dev:

```python
# Deployed: Unix socket
server = HTTPServer(UnixSocketAddress("/var/run/asya/asya-runtime.sock"))

# Local testing: TCP
server = HTTPServer(("127.0.0.1", 8080))
```

This means handlers can be tested **directly** -- no sidecar, no queue, no
Docker, no K8s. Just start `asya_runtime.py` locally, send HTTP requests:

```bash
ASYA_HANDLER=my_module.process \
  python asya_runtime.py  # listens on TCP

curl -X POST http://127.0.0.1:8080/invoke \
  -H "Content-Type: application/json" \
  -d '{"id":"test","route":{"prev":[],"curr":"a","next":[]},"headers":{},"payload":{"text":"hello"}}'
```

**What this tests**: handler logic, payload transformation, error handling,
generator/SSE streaming -- all using the same code path as production.

**What this does NOT test**: queue consumption, sidecar routing, autoscaling,
multi-actor pipelines.

**Important**: This is a **local testing** capability, not a deployment
strategy. The HTTP protocol exists to make the runtime debuggable and testable
(`curl --unix-socket` in pods, `curl localhost:8080` locally). It should not
be confused with the build/deploy levels described in
`.aint/aints/asya-lab/research-seamless-build.md` -- those are about how code
gets into K8s. This is about how you test it before it gets there.

**Design considerations for the RFC**:
- `asya test handler.py` could start runtime + send test fixtures
- Jupyter magic `%asya_test process` could wrap the HTTP call
- Test fixtures could be JSON files or inline payloads
- pytest integration via `asya_test_client()` fixture
- Could combine with docker-compose for multi-actor local testing (runtime
  containers talk HTTP, a lightweight router replaces the sidecar)

---

## Skaffold / Tilt for Local Code Sync

Skaffold and Tilt are local development tools that watch files and sync code
changes into running K8s pods without rebuilding images.

**Skaffold** (Google, YAML config):
- File sync: `src/**/*.py` -> `/app` in container (~1-2s)
- Dependency changes (requirements.txt) trigger full rebuild (~30s)
- `skaffold dev` watches files, auto-syncs, cleans up on Ctrl+C
- Python buildpacks auto-sync NOT available yet (Go, Java, Node.js only)

**Tilt** (Docker-owned, Apache 2.0, Python/Starlark config):
- Live update with decision tree: code change -> sync (1s), deps change ->
  in-container pip install (10s), Dockerfile change -> rebuild (60s)
- Built-in web UI for monitoring multi-service apps
- Python config more natural for DS than Skaffold's YAML

**Both are local testing / inner-loop tools**, not deployment strategies.
They require a running K8s cluster and kubectl access. Consider them for
the local testing RFC alongside mirrord and direct HTTP testing.

**mirrord** (Apache 2.0) is also in this category -- process-level
interception that runs local Python against remote staging queues. Has
"queue splitting" for SQS/RabbitMQ. Lighter than Skaffold/Tilt (no Docker
build needed at all). See research-seamless-build.md section 2.5 for details.
