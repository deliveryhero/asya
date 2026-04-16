---
description: "Components index: sidecar, runtime, gateway, crew, crossplane, state proxy, CLI, flow compiler"
---

# Components

## Core — Runtime Infrastructure

The components that make actors run and communicate.

| Component | Description |
|-----------|-------------|
| [core-sidecar.md](core-sidecar.md) | Envelope router injected into actor pods — queue consumption, message routing, retries, metrics |
| [core-runtime.md](core-runtime.md) | Python handler execution environment — Unix socket server, handler loading, async support |
| [core-gateway.md](core-gateway.md) | MCP/A2A HTTP bridge — sync-to-async translation, task state, SSE streaming |
| [core-crew.md](core-crew.md) | System actors — x-sink (results), x-sump (DLQ), x-pause/x-resume (human-in-the-loop) |
| [core-crossplane.md](core-crossplane.md) | Crossplane XRD and Compositions — declarative actor deployment with inline sidecar rendering |
| [core-state-proxy.md](core-state-proxy.md) | Virtual persistent state — filesystem emulation backed by S3, GCS, Redis, or NATS KV |
| [core-actor.md](core-actor.md) | AsyncActor resource behavior — label propagation, status model |

## Lab — Developer Tooling

Tools for building, debugging, and interacting with the actor mesh.

| Component | Description |
|-----------|-------------|
| [lab-flow-compiler.md](lab-flow-compiler.md) | Flow DSL compiler — transforms Python control flow into CPS message-passing chains |
| [lab-cli.md](lab-cli.md) | CLI reference — `asya flow`, `asya mcp`, `asya build`, `asya k` |
| lab-sdk.md | *(planned)* Python SDK for actor development |
| lab-vscode.md | *(planned)* VS Code extension |
| lab-jupyter.md | *(planned)* JupyterLab magic commands |
