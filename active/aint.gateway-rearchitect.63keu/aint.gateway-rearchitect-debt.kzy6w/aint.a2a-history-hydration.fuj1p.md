---
title: "A2A history hydration from state-proxy-s3"
status: open
priority: 3
tags: [gateway-rearchitect, a2a]
---

RFC 4.3 says tasks/get needs conversation history from state-proxy-s3 sidecar.
Currently StoreAdapter.Get only reads from mesh-api (status + data). History
artifacts are in S3 via state-proxy. RFC says SHOULD not MUST.

**Fix:** Add optional state-proxy-s3 client to StoreAdapter. When present,
read conversation history from S3 and populate task.History in Get response.
