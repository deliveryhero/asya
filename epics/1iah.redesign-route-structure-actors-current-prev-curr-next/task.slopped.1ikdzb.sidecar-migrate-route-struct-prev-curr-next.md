---
title: "Sidecar: migrate Route struct to prev/curr/next"
priority: 1 # high
type: task
---

Update Go Route struct in src/asya-sidecar/pkg/messages/message.go from {Actors []string, Current int} to {Prev []string, Curr string, Next []string}. Update all Route methods (GetCurrentActor, GetNextActor, HasNextActor, IncrementCurrent) to use new schema. Update all sidecar routing logic in router.go. Update all unit tests.
