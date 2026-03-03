---
title: "Build connector base framework (HTTP/Unix-socket server, health, shutdown)"
priority: 1 # high
tags:
  - pr:195
---


Build the reusable base framework that all state proxy connectors will extend:

- HTTP server listening on a Unix socket at /var/run/asya/state/{name}.sock
- Request routing to StateProxyConnector method implementations
- Health check endpoint for readiness probes
- Graceful shutdown handling
- Structured JSON error response formatting
- Dockerfile base image for connector containers

Container naming convention: asya-state-proxy-{name}.

This is the shared infrastructure that s3-buffered-lww, redis-buffered-cas, and all future connectors will build on.

Phase: 1 (Connector interface and framework)
