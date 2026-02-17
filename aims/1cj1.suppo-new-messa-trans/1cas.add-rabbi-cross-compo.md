---
title: Add RabbitMQ Crossplane composition
status: open
priority: 2 # medium
type: task
---

Add composition-rabbitmq.yaml for Crossplane. The operator already supports RabbitMQ via the pluggable transport layer (internal/transports/), and code+tests already work with RabbitMQ. Only the Crossplane composition is missing — currently only composition-sqs.yaml exists. This is a known gap: RabbitMQ transport is not yet supported in the Crossplane model. Deliverables: composition-rabbitmq.yaml, update XRD if needed, E2E test profile for rabbitmq.


---
**Close reason**: Implemented RabbitMQ Crossplane composition, conditional AWS providers, compositionSelector on all claims, injector RabbitMQ support, and E2E profile updates


---
_Migrated from beads `asya-3vg8`_
