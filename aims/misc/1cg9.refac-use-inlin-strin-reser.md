---
title: "Refactor: Use inline strings for reserved names, update golangci"
status: open
priority: 4 # backlog
type: task
---

## Summary

Remove const variables for hardcoded reserved names like "asya-sidecar" and use inline strings instead. This makes code navigation easier (search for "asya-sidecar" finds all usages) and reduces indirection.

## Current State

```go
const (
    sidecarName          = "asya-sidecar"
    runtimeContainerName = "asya-runtime"
    // ...
)

// Usage scattered across file
if container.Name == sidecarName {
```

## Proposed State

```go
// Use inline strings for reserved names (easier to search/navigate)
if container.Name == "asya-sidecar" {
```

## Golangci-lint Update

The linter may flag this as "magic string". Update `.golangci.yml` to:
- Disable goconst for specific patterns matching `asya-*`
- Or add nolint directives where appropriate
- Or configure goconst to ignore strings used < N times

## Files to Update

- `src/asya-operator/internal/controller/asya_controller.go` - Remove const, use inline
- `.golangci.yml` - Update goconst configuration
- Potentially other Go files that use these constants

## Acceptance Criteria

- [ ] Reserved names used inline (no const variables)
- [ ] golangci-lint passes without warnings
- [ ] Code searchability improved
- [ ] All tests pass


---
_Migrated from beads `asya-4f2`_
