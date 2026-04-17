---
title: "Fix G120 gosec: add MaxBytesReader to OAuth form parsing"
status: open
priority: 2
tags: [gateway-rearchitect, security]
---

**Source:** golangci-lint findings when reviewing PR2 ([#444](https://github.com/deliveryhero/asya/pull/444)).

**Problem:** `internal/oauth/server.go` (lines 250-295) calls `r.ParseForm()`
and `r.FormValue()` without wrapping `r.Body` in `http.MaxBytesReader`. Gosec
G120 flags this: a client can send an arbitrarily large request body,
potentially causing memory exhaustion (DoS).

Affected endpoints:
- `POST /oauth/token` — handles `authorization_code` and `refresh_token` grants
- Form fields: `grant_type`, `code`, `client_id`, `redirect_uri`,
  `code_verifier`, `refresh_token`

**Fix:** Add `r.Body = http.MaxBytesReader(w, r.Body, 1*1024*1024)` before
`r.ParseForm()` in the token endpoint handler. 1MB is generous for OAuth forms.

**Currently suppressed** in `.golangci.yml` via gosec G120 exclusion.
Remove exclusion after fix.
