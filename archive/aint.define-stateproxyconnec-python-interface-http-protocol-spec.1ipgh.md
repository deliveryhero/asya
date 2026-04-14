---
title: Define StateProxyConnector Python interface and HTTP protocol spec
status: merged
priority: 1
tags:
  - pr:195
---

Define the core `StateProxyConnector` ABC with `KeyMeta`, `ListResult` data types, and the 6 interface methods: `read()`, `write()`, `exists()`, `stat()`, `list()`, `delete()`.

Document the HTTP-over-Unix-socket protocol mapping:
- GET /keys/{key} -> read()
- PUT /keys/{key} -> write()
- HEAD /keys/{key} -> exists()/stat()
- GET /keys/?prefix={p}&delimiter=/ -> list()
- DELETE /keys/{key} -> delete()

Define the error response JSON format and HTTP status code mapping (404->FileNotFoundError, 409->FileExistsError, etc).

This is the foundational contract that all connectors and the runtime depend on. See RFC sections: "Connector Interface", "Protocol: HTTP over Unix Socket", "Error Mapping".

Phase: 1 (Connector interface and framework)
