---
title: Check GetTasks Implementation
status: open
priority: 2
---

See gateway's `main.go`:
```go
	// Wire state proxy reader for GetTask history/artifact hydration.
	// When ASYA_PERSISTENCE_MOUNT is set, the gateway reads persisted envelope state
	// from the same filesystem mount used by x-sink / x-sump / x-pause crew actors.
	// If unset, history and artifacts are omitted from GetTask responses (spec-compliant).
	var spReader stateproxy.Reader
	if persistMount := os.Getenv("ASYA_PERSISTENCE_MOUNT"); persistMount != "" {
		slog.Info("State proxy reader enabled", "mount", persistMount)
		spReader = stateproxy.NewFileReader(persistMount)
	}
```

Ideally, gateway doesn't need to know this detail - check if `GetTasks` really requires this.
