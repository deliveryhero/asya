---
title: Rename Envelope→Message in Go code (sidecar, gateway, operator)
status: merged
priority: 2
parent: 00000
---

Rename all Envelope structs, variables, functions, and types to Message in Go components:
- asya-sidecar: envelope.go, envelope types, handler functions
- asya-gateway: envelope tracking, status endpoints
- asya-operator: any envelope references

This is a breaking change for internal APIs but not for external consumers.


---
**Close reason**: Completed as part of the envelope→message/task rename PR


---
_Migrated from beads `asya-58u`_
