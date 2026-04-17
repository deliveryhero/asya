---
title: "A2A history hydration from state-proxy-s3"
status: open
priority: 3
tags: [gateway-rearchitect, a2a]
---

**Source:** RFC conformance review of PR2 ([#444](https://github.com/deliveryhero/asya/pull/444)). RFC section 4.3.

**Problem:** A2A `tasks/get` returns status and artifacts from mesh-api, but
conversation history (previous messages in the task context) is stored in S3
via state-proxy, not in mesh-api's PG kv table. `StoreAdapter.Get`
(`internal/a2aadapter/store.go:33`) only reads mesh-api.

**RFC says:** "A2A tasks/get needs conversation history... state-proxy-s3
sidecar." Marked as SHOULD, not MUST — acceptable to defer.

**Fix:** Add optional state-proxy-s3 HTTP client to `StoreAdapter`. When the
sidecar is available (detected via env var or socket), read conversation
history from S3 and populate `task.History` in the Get response.

**Files:**
- `src/asya-gateway/internal/a2aadapter/store.go:33` — Get method
- RFC section 4.3 — history requirement
