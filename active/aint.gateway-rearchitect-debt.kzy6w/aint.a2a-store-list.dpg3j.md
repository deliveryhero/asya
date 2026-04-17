---
title: "Wire A2A StoreAdapter.List to mesh-api list endpoint"
status: open
priority: 3
tags: [gateway-rearchitect, a2a]
---

**Source:** Code review of PR2 ([#444](https://github.com/deliveryhero/asya/pull/444)).

**Problem:** `StoreAdapter.List` (`internal/a2aadapter/store.go:82`) returns
empty results with a warning log. The mesh-api already has
`GET /api/v1/mesh/?status=X&limit=N&offset=N` that supports filtering and
pagination.

**Fix:** Call `meshClient.List()` (needs new method on `meshclient.Client`),
translate A2A `ListTasksRequest` (pageSize, pageToken) into mesh-api query
params, and map response `MessageStatus` objects to `a2alib.Task`.

**Files:**
- `src/asya-gateway/internal/a2aadapter/store.go:82` — List stub
- `src/asya-gateway/internal/meshclient/client.go` — needs List method
- `src/asya-gateway/internal/mesh/list.go` — mesh-api list handler (already works)
