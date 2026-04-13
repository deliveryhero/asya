---
title: "Gateway: add Headers field to ActorMessage for API-driven route overrides"
status: open
priority: 3
parent: 2w664
---

ActorMessage struct in asya-gateway has no Headers field. Add headers support so x-asya-route-override can be injected via the MCP gateway API, enabling API-driven A/B routing without direct queue injection.
