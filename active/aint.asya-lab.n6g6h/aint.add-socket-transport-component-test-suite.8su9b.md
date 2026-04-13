---
title: Add socket transport component test suite
status: open
priority: 2
assignee: Artem Yushkovskiy
parent: n6g6h
dependencies:
  - cavw
tags:
  - worktree:.worktrees/asya-lab/8su9.add-socket-transport-component-test-suite
  - branch:asya-lab/8su9.add-socket-transport-component-test-suite
  - pr:300
---

Status: PR closed for now, deferred for the future.


Create testing/component/transport/ — a Docker Compose component test for SocketTransport methods in isolation.

Scope: tests only the Transport interface (Send, Receive, Requeue, Ack, Close, SendWithDelay).
No sidecar, no runtime, no routing logic, no x-sink/x-sump.

Implementation (Option A): a small Go binary cmd/socket-tester in src/asya-sidecar that exercises
SocketTransport directly. Docker Compose mounts a named volume as the mesh dir and runs the binary
as the tester container; exit code 0 = pass.

Scenarios:
- Basic send/receive: body delivered unchanged
- Large payload (1MB): framing with 4-byte length prefix handles big messages
- FIFO ordering: 10 sequential sends arrive in order
- Requeue: requeued message re-delivered before next network message
- Sender retry: sender starts before receiver socket exists, retries until ready
- Context cancellation: Receive unblocks promptly on ctx.Done()
- SendWithDelay: returns ErrDelayNotSupported
- Cross-container: receiver and sender in separate containers sharing mesh volume

Will be extended in dxo1 to parametrize across transports.
