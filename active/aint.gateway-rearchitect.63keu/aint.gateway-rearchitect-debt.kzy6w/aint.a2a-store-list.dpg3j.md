---
title: "Wire A2A StoreAdapter.List to mesh-api list endpoint"
status: open
priority: 3
tags: [gateway-rearchitect, a2a]
---

StoreAdapter.List returns empty results with a warning log. The mesh-api
has a GET /api/v1/mesh/ list endpoint that supports filtering and pagination.

**Fix:** Translate A2A ListTasksRequest (pageSize, pageToken) into mesh-api
query params (limit, offset). Map response back to A2A Task objects.
