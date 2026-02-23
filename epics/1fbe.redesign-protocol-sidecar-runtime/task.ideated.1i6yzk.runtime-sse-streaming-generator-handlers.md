---
title: Runtime SSE streaming for generator handlers
priority: 2 # medium
type: task
dependencies:
  - 1fbe/1iof6x
---

Add SSE (text/event-stream) response mode for generator and async-generator handlers.

Scope:
- Runtime auto-detects handler type (return vs generator) and selects response format
- JSON response for return-based handlers (from T1)
- SSE (text/event-stream) for generator handlers
- Event types: downstream (yielded output frames), upstream (partial/token frames), done (completion sentinel), error (handler exception)
- Generator yields dict -> downstream event
- Generator yields with upstream marker -> upstream event
- End of iteration -> done event
- Exception during iteration -> error event

Key files:
- src/asya-runtime/asya_runtime.py (_handle_payload_mode_streaming, _handle_envelope_mode_streaming, _handle_request_streaming)

Unit tests required.
