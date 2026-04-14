---
title: "Injector: State proxy sidecar injection (containers, volumes, ASYA_STATE_PROXY_MOUNTS)"
status: merged
priority: 1
tags:
  - pr:195
---

Update asya-injector mutating webhook to handle stateProxy spec:

1. Add state-sockets emptyDir volume to pod spec

2. For each stateProxy entry, inject a sidecar container:
   - Name: asya-state-proxy-{name}
   - Image: from connector.image
   - Env: CONNECTOR_SOCKET=/var/run/asya/state/{name}.sock + connector.env entries
   - Resources: from connector.resources (if specified)
   - Volume mount: state-sockets at /var/run/asya/state

3. Add state-sockets volume mount to runtime container at /var/run/asya/state

4. Generate and inject ASYA_STATE_PROXY_MOUNTS env var into runtime container:
   - Format: {name}:{path}:{options}[;...]
   - Determine write mode (buffered/passthrough) from connector image name or registry
   - Example: meta:/state/meta:write=buffered;media:/state/media:write=passthrough

5. Handle edge cases: no stateProxy -> no changes, empty array -> no changes

Phase: 3 (Injector and XRD integration)
