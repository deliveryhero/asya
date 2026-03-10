---
title: Add socket transport component test suite
priority: 2 # medium
dependencies:
  - cavw
---

Create testing/component/transport/ — a dedicated Docker Compose test suite for the socket transport.

The tester container acts as x-sink AND x-sump (listens on those sockets directly), so no crew actors or message broker infrastructure is needed. Tests inject envelopes by connecting to actor sockets and capture results from x-sink/x-sump listeners.

Covers all transport edge cases:
- Happy path: message delivered echo actor → x-sink
- Error → x-sump
- OOM → x-sump
- Timeout → x-sump
- Fan-out (multiple yields) → multiple messages in x-sink
- Empty response (abort) → x-sink
- Large payload (framing correctness)
- Unicode content
- Null values
- Multi-hop routing (actor A routes to actor B → x-sink)
- Route override via ABI SET .route.next
- Retry behavior (fail-once handler)
- FIFO message ordering
- Purge/isolation between tests

Will be extended in dxo1 to parametrize across transports.
