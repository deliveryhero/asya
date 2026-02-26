# RFC: Cog-based ML Runtime for Asya

**Status:** Draft
**Author:** [User] / Gemini
**Date:** 2026-02-26
**Epic:** [Integration of ML Runtimes]

## 1. Context & Problem Statement

Currently, `asya.sh` runtimes are general-purpose Python containers. For ML workloads, users struggle with:

1. **CUDA/CUDNN versioning:** Complex dependency chains.
2. **Standardized Interfaces:** Inconsistent ways to define "inputs" for models.
3. **Efficiency:** Standard Python HTTP servers (Flask/FastAPI) add overhead compared to Asya's sidecar-runtime UDS protocol.

**Cog** solves (1) and (2) but brings its own Go-based orchestration layer (`coglet`/`cog-runtime`) which overlaps with and conflicts with Asya’s `sidecar`.

## 2. Proposed Architecture

We will integrate Cog by stripping the Cog Orchestrator and making the **Asya Sidecar** talk directly to the **Cog Python Worker** via a Unix Domain Socket (UDS).

### 2.1 The Build Pipeline

Instead of a standard `cog build`, the Asya-Cog flow will:

1. Ingest a `cog.yaml` and `predict.py`.
2. Run `cog debug > Dockerfile` to generate the optimized, multi-stage ML environment.
3. **Post-Process the Dockerfile:**
* Remove the `COPY --from=cog /usr/local/bin/cog`.
* Set the `ENTRYPOINT` to `python3 -m cog.server.worker --unnamed-socket /tmp/asya.sock`.


4. Build the final `asya-runtime` image.

## 3. Implementation Details

### 3.1 Protocol Translation

Asya sidecars use **HTTP-over-Unix**. The Cog Worker uses **JSON-RPC-over-Unix**.
The Asya Sidecar will act as a protocol bridge:

| Asya (HTTP) | Translation Layer | Cog Worker (JSON-RPC) |
| --- | --- | --- |
| `POST /invoke` | Convert body to `params` | `{"method": "run", "params": {...}}` |
| (Streaming) | Parse JSON-RPC events | `{"event": "logs", ...}` |
| `200 OK` | Extract final `output` | `{"event": "completed", ...}` |

### 3.2 Lifecycle Management

The Sidecar will manage the `cog.server.worker` lifecycle:

* **Init:** Sidecar creates the UDS and spawns the Worker.
* **Warm-up:** Sidecar waits for Cog’s `setup()` to complete (indicated by the `SETUP_COMPLETED` signal from the worker).
* **Execution:** Sidecar pipes actor messages to the worker socket.

## 4. Advantages

* **Stripped Runtime:** We eliminate the Axum server, PermitPool, and HTTP Transport logic from the container, saving ~50MB and reducing attack surface.
* **Direct UDS Path:** No double-proxying (Sidecar -> Cog Proxy -> Worker). It becomes Sidecar -> Worker.
* **ML Best Practices:** Asya users get "free" GPU optimization and Pydantic validation via Cog’s `BasePredictor`.

## 5. Next Steps

1. **PoC:** Manually modify a `cog debug` Dockerfile and verify `asya-sidecar` can communicate with `cog.server.worker`.
2. **Build Integration:** Add a `cog` runtime type to the `asya` CLI/build-system.
3. **Documentation:** Provide a guide for users to migrate standard `predict.py` models to Asya actors.
