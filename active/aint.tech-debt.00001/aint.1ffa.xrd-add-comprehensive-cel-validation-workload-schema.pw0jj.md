---
title: "XRD: Add comprehensive CEL validation for workload schema"
status: open
priority: 3
tags:
  - type:feature
---

## Summary

Add comprehensive CEL validation rules to the XAsyncActor XRD to prevent users from defining operator-injected resources. This provides immediate feedback at admission time instead of confusing errors during reconciliation.

## Prerequisite

Depends on: "Refactor: Unify injected mounts under /opt/asya directory"
The validation rules reference the new unified mount structure.

## Proposed CEL Validation Rules

### Container Requirements
- Exactly one container named 'asya-runtime' (already implemented)
- No container named 'asya-sidecar' (reserved)
- asya-runtime must NOT have 'command' (already implemented)
- asya-runtime MUST have ASYA_HANDLER env var

### Forbidden Env Vars (injected)
- ASYA_SOCKET_DIR
- ASYA_ENABLE_VALIDATION

### Forbidden Volume Mounts (injected)
- Mount name 'asya-reserved'
- Mount path /opt/asya/ or any subpath

### Forbidden Volumes (injected)
- Volume name 'asya-reserved'

## Example CEL Rules

```yaml
x-kubernetes-validations:
  # No container named 'asya-sidecar' (reserved)
  - rule: "!self.template.spec.containers.exists(c, c.name == 'asya-sidecar')"
    message: "container name 'asya-sidecar' is reserved"

  # asya-runtime MUST have ASYA_HANDLER env var
  - rule: "self.template.spec.containers.filter(c, c.name == 'asya-runtime').all(c, has(c.env) && c.env.exists(e, e.name == 'ASYA_HANDLER'))"
    message: "asya-runtime container must have ASYA_HANDLER environment variable"

  # No ASYA_SOCKET_DIR on runtime (injected)
  - rule: "self.template.spec.containers.filter(c, c.name == 'asya-runtime').all(c, !has(c.env) || !c.env.exists(e, e.name == 'ASYA_SOCKET_DIR'))"
    message: "ASYA_SOCKET_DIR is injected and cannot be defined"

  # No mount at /opt/asya (reserved)
  - rule: "self.template.spec.containers.filter(c, c.name == 'asya-runtime').all(c, !has(c.volumeMounts) || !c.volumeMounts.exists(v, v.mountPath.startsWith('/opt/asya')))"
    message: "/opt/asya is reserved for operator-injected resources"

  # No volume named 'asya-reserved' (injected)
  - rule: "!has(self.template.spec.volumes) || !self.template.spec.volumes.exists(v, v.name == 'asya-reserved')"
    message: "volume 'asya-reserved' is injected and cannot be defined"
```

## Acceptance Criteria

- [ ] All CEL validation rules implemented
- [ ] Clear error messages for each violation
- [ ] Tests for each validation rule
- [ ] Documentation updated


_Migrated from beads `asya-tiz`_
