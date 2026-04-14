---
title: Add DeadlineAt to message Status struct and ParseDeadline helper
status: merged
priority: 2 # medium
tags:
  - pr:212
---


## Scope

Add `DeadlineAt string` field to the `Status` struct in `src/asya-sidecar/pkg/messages/message.go` and a `ParseDeadline() (time.Time, bool)` helper method on Message.

## Details

- Field: `DeadlineAt string` with json tag `deadline_at,omitempty`
- Helper: `func (m *Message) ParseDeadline() (time.Time, bool)` — parses RFC3339, returns zero+false if missing or malformed
- Unit tests: valid RFC3339, empty string, malformed value, zero time

## Files
- `src/asya-sidecar/pkg/messages/message.go`
- `src/asya-sidecar/pkg/messages/message_test.go`

## Wave
Wave 1: Sidecar Foundation
