---
title: "Implement storing exposed flows in gateway's DB to do"
status: ideated
priority: 2
type: epic
---

Flow (its entrypoint + input signature, to be exposed as MCP tool or A2A agent) - is a business logic information not K8s/infra, so it should be stored in gateway's DB. Note that there's no AsyncFlow CRD, we just mark actors belonging to a flow with asya.sh/flow=..., see ADR .aint/epics/1iqd.design-flow-workflow/adr-async-flow-crd-vs-labels.md.
