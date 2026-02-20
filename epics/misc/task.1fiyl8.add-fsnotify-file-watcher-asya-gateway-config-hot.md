---
title: Add fsnotify file watcher to asya-gateway for config hot-reload
status: open
priority: 2 # medium
type: task
tags:
  - type:feature
---



Add fsnotify-based file watcher to asya-gateway that detects changes to the mounted config directory and triggers config reload (LoadFromDir). This enables dynamic tool registration without gateway restarts.

Implementation:
- Add fsnotify dependency to asya-gateway
- Watch ASYA_CONFIG_PATH for file changes (CREATE, WRITE, REMOVE events)
- On change: debounce (500ms), call LoadFromDir/LoadConfig, re-register tools
- Thread-safe tool registry updates (existing requests must complete)
- Log tool additions/removals at INFO level

~20-30 lines of Go in main.go or a new internal/config/watcher.go file.

Enables the GatewayConfig XRD pattern where Crossplane updates the ConfigMap and kubelet refreshes the volume mount.


---
_Migrated from beads `asya-j2vk`_
