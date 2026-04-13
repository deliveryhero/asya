---
title: Smart entrypoint/exitpoint detection and flow_role labeling
status: rejected
priority: 2
dependencies:
  - o8ql
---

Implement automatic entry/exit detection: first user actor is entrypoint (no empty start router), last actors before each return are exitpoints (no empty end router). flow_role vocabulary: entry, exit, entryexit, router, actor. Single-valued asya.sh/flow-role K8s label. entryexit for single-actor flows. Eliminates empty start/end routers (subsumes aint 20c9). See RFC sections: Entrypoint and exitpoint detection, flow_role vocabulary.
