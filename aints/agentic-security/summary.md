---
title: Agentic security
priority: 1 # high
---

Gateway security model: dual-deployment split (api + mesh), protocol-native
auth (A2A API key/JWT, MCP OAuth 2.1), network isolation for mesh routes.

See `rfc.md` for full design. Phases:
1. Dual-deployment split + wire existing A2A auth [1fuy]
2. MCP API key auth [b51i]
3. MCP OAuth 2.1 spec compliance [rcvm]
4. Enterprise auth — OAuth2/OIDC for both protocols [iu97]

Orthogonal tasks (unchanged):
- Secrets management research [1fdf]
- TLS/mTLS local dev setup [1f63]
