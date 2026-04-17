---
title: "Fix G120 gosec: add MaxBytesReader to OAuth form parsing"
status: open
priority: 2
tags: [gateway-rearchitect, security]
---

internal/oauth/server.go calls r.ParseForm() and r.FormValue() without
http.MaxBytesReader. Gosec G120 flags this as potential memory exhaustion
(client can send arbitrarily large form data).

**Fix:** Wrap r.Body with http.MaxBytesReader before ParseForm calls.
Currently suppressed in .golangci.yml (path-specific exclusion).
