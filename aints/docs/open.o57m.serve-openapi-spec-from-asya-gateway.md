---
title: Serve OpenAPI spec from asya-gateway
priority: 3 # low
dependencies: [agentic-security/4iga]
---

## Goal

Serve a machine-readable OpenAPI 3.1 spec from `asya-gateway` so that clients
can introspect the API without reading the source or docs.

## Proposed endpoints

```
GET /openapi.json   → OpenAPI 3.1 JSON spec
GET /openapi.yaml   → OpenAPI 3.1 YAML spec (optional)
```

Both are public (no auth required), mirroring the `.well-known/` pattern.

## Implementation options

**Option A — Manual OpenAPI YAML (recommended for v0)**

- Write `src/asya-gateway/openapi.yaml` by hand (or derive from
  `docs/internal/gateway-api-spec.md`).
- Register a static file handler in `main.go`:
  ```go
  mux.HandleFunc("GET /openapi.json", serveOpenAPIJSON)
  ```
- Zero new dependencies; spec lives in the repo and can be reviewed in PRs.
- Downside: must be updated manually when routes change.

**Option B — swaggo/swag annotations**

- Add `// @Summary`, `// @Router`, etc. comments to all handler functions.
- Run `swag init` at build time to generate `docs/swagger.json`.
- Adds a build-time code-gen step and `swaggo` dependency.
- Upside: spec is always in sync with handlers.

**Recommendation**: Start with Option A (manual spec derived from
`docs/internal/gateway-api-spec.md`). Add a CI lint step (`spectral lint`)
to catch schema errors. Switch to Option B if the spec drifts too often.

## Note on auto-generation

`asya-gateway` uses standard `net/http` directly (no gin/echo/chi), which has
no built-in route registry that can be walked. Automatic spec generation
requires either swaggo annotations (Option B) or a custom reflection approach.

## Scope

- Register `/openapi.json` on `api` and `testing` gateway modes.
- The spec should cover all routes in `docs/internal/gateway-api-spec.md`.
- Do NOT serve on `mesh` mode (internal routes are not for external consumers).

## References

- `docs/internal/gateway-api-spec.md` — source-of-truth route reference
- `src/asya-gateway/internal/server/` — route registration
