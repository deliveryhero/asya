---
title: "Consolidate state proxy images: asya-state-proxy-py and asya-state-proxy-go"
status: open
priority: 2 # medium
---

Merge 7 per-flavor Dockerfiles into two images: asya-state-proxy-py (all Python connectors, runtime ASYA_CONNECTOR selection) and asya-state-proxy-go (pg-kv binary). Add both to build-images.sh.
