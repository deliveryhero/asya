---
title: "Refactor: Unify injected mounts under /opt/asya directory"
status: open
priority: 2 # medium
type: task
tags:
  - type:feature
---



## Summary

Consolidate all operator-injected volumes and mounts under a single reserved directory `/opt/asya/` with clear subdirectory structure. This simplifies the injection logic, makes it obvious which paths are operator-managed, and provides a consistent namespace for future extensions.

## Current State (fragmented)

| Resource | Current Path | Volume Name |
|----------|--------------|-------------|
| Socket | /var/run/asya/asya-runtime.sock | socket-dir |
| Runtime script | /opt/asya/asya_runtime.py | asya-runtime |
| Tmp directory | /tmp | tmp |

**Problems:**
- Paths scattered across /var/run, /opt, /tmp
- Volume names inconsistent (socket-dir vs asya-runtime)
- /tmp conflicts with user mounts
- Hard to document what's "reserved by Asya"

## Proposed State (unified)

| Resource | New Path | Volume Name |
|----------|----------|-------------|
| Base directory | /opt/asya/ | asya-reserved |
| Socket | /opt/asya/sockets/runtime.sock | (subpath) |
| Runtime script | /opt/asya/runtime/asya_runtime.py | (subpath) |
| Tmp directory | /opt/asya/tmp/ | (subpath) |
| Ready flag | /opt/asya/sockets/runtime-ready | (subpath) |

**Single volume mount:** One emptyDir volume `asya-reserved` mounted at `/opt/asya/`
**ConfigMap mount:** Runtime script mounted as subpath at `/opt/asya/runtime/asya_runtime.py`

## Files to Update

### Operator Code
- `src/asya-operator/internal/controller/asya_controller.go`:
  - Update constants: socketVolume, tmpVolume, runtimeVolume, runtimeMountPath
  - Update injectSidecar() function
  - Update probe commands (socket path, ready flag path)
  - Update ASYA_SOCKET_DIR env var value

### Sidecar Code
- `src/asya-sidecar/` - Update socket path defaults and env var handling

### Runtime Code
- `src/asya-runtime/asya_runtime.py` - Update socket path, ready flag path

### Testing
- Update all integration tests that reference socket paths
- Update E2E tests
- Update test fixtures

### Documentation
- `AGENTS.md` - Document new path structure
- `docs/architecture/operator.md` - Document injection details

### XRD/Composition
- `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml` - Update validation rules

## Environment Variables

| Variable | Old Value | New Value |
|----------|-----------|-----------|
| ASYA_SOCKET_DIR | /var/run/asya | /opt/asya/sockets |

## Migration Notes

- This is a breaking change for any code that hardcodes paths
- Sidecar and runtime must be updated together
- All tests must pass before merge

## Acceptance Criteria

- [ ] Single volume `asya-reserved` contains all Asya resources
- [ ] All mounts under /opt/asya/ prefix
- [ ] Socket at /opt/asya/sockets/runtime.sock
- [ ] Runtime at /opt/asya/runtime/asya_runtime.py
- [ ] Tmp at /opt/asya/tmp/
- [ ] Ready flag at /opt/asya/sockets/runtime-ready
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] All E2E tests pass
- [ ] Documentation updated
- [ ] XRD validation updated


---
_Migrated from beads `asya-kny`_
