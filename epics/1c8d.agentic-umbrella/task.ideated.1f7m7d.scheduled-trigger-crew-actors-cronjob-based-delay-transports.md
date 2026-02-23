---
title: Scheduled trigger crew actors (CronJob-based delay for transports without SendWithDelay)
priority: 3 # low
type: task
tags:
  - type:feature
---




For transports that don't support native delayed message delivery (Kafka, Redis Streams, Google Pub/Sub), implement a CronJob-based scheduler crew actor that can hold and re-deliver messages on a schedule. This enables the error-handler retry flow for all transports. Linked to error handling RFC (asya-y4kr) - error handler will route to this actor when transport returns 'not implemented' for SendWithDelay.


---
_Migrated from beads `asya-013s`_
