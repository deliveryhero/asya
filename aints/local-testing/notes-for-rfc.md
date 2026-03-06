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
