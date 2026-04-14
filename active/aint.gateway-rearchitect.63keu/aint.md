---
title: "RFC: Replace asya-gateway with agentgateway + asya-dispatcher"
status: open
priority: 1
tags:
  - architecture
  - rfc
---

Replace asya-gateway (~7,150 LOC) with agentgateway (MCP, auth) + asya-dispatcher
(~2,000 LOC, two-port Go service). See [rfc.md](rfc.md) for full design.
