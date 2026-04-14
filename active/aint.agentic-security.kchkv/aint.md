---
title: Agentic security
status: open
priority: 2
---

Gateway security model: dual-deployment split (api + mesh), protocol-native
auth (A2A API key/JWT, MCP OAuth 2.1), network isolation for mesh routes.

See `rfc.md` for full design.

## v0 scope

Implemented (merged):
1. Dual-deployment split + wire existing A2A auth [1fuy] — merged PR #269
2. MCP API key auth [b51i] — merged PR #271
3. MCP OAuth 2.1 spec compliance [rcvm] — merged PR #271

Remaining:
- K8s Secrets for AsyncActor actors [wcnw] — needed for AI API tokens in PoC
- Internal security docs in docs/internal/ [4iga] — reconcile RFC with implementation

## Post-v0

- Enterprise auth — OAuth2/OIDC for both protocols [iu97]
- External secrets: Vault, ESO, cloud secret managers [1fdf] — depends on wcnw
- TLS/mTLS deployment docs [1f63]
