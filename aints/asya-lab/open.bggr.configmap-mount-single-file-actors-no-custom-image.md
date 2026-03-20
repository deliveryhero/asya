---
title: ConfigMap-mount single-file actors (no custom image)
priority: 2 # medium
---

## Context

Asya actors currently require a custom container image per handler package. But for simple single-file handlers (one `.py` file, no heavy dependencies beyond what's in the base image), building a full Docker image is overkill. The same pattern already exists for **router actors**: the compiler generates Python code, bakes it into a ConfigMap, and mounts it on `python:3.13-slim` (the `router_image`). This pattern should be available for user handler actors too.

## Problem Statement

A data scientist writes a single-file handler:
```python
# actors/sentiment/handler.py
def analyze(payload: dict) -> dict:
    text = payload["text"]
    return {"sentiment": "positive" if "good" in text else "negative"}
```

Today, they must: write a Dockerfile, add a skaffold artifact, build the image, push it. For a trivial handler with no pip dependencies, this is unnecessary friction.

## Proposed Design

### Detection

The compiler detects a "ConfigMap-mountable" handler when:
1. `inspect.getfile(handler)` resolves to a single `.py` file
2. The file has no matching skaffold artifact (no build context contains it)
3. The file has no `pyproject.toml` / `setup.py` ancestor within the project

OR the user explicitly annotates: `# asya: configmap` in the handler file.

### Compilation

When detected, the compiler:
1. Does NOT look for a skaffold artifact or image
2. Uses `templates.router_image` (e.g., `python:3.13-slim`) as the base image
3. Emits the handler code as a ConfigMap (same mechanism as router ConfigMaps)
4. Sets `ASYA_HANDLER` to the module name derived from the ConfigMap mount path
5. The resulting AsyncActor XR looks like a router actor but with user handler code

### ConfigMap Structure

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: <flow-name>-handlers
  labels:
    asya.sh/flow: <flow-name>
    asya.sh/managed-by: asya-compiler
data:
  handler_analyze.py: |
    def analyze(payload: dict) -> dict:
        ...
```

The actor mounts this ConfigMap at `/opt/asya/handlers/` and sets:
- `ASYA_HANDLER=handler_analyze.analyze`
- `PYTHONPATH=/opt/asya/handlers`

### Limitations

- No pip dependencies beyond what's in `router_image`
- Single file only (no multi-file package)
- No GPU/CUDA support
- ConfigMap size limit (1MB) -- but single handler files are typically <10KB
- If the handler grows beyond these limits, user upgrades to a proper image (add Dockerfile + skaffold artifact)

### Progressive Complexity Path

```
Single-file handler (ConfigMap) -> needs deps -> Dockerfile + skaffold artifact -> needs GPU -> custom base image
```

### Related Docs

- Router actor ConfigMap mechanism: `rfc.md` S7.3.3 (compiler/templates/configmap_routers.yaml)
- Build system research: `research-build-system.md` (D2: Skaffold as source of truth)
- Compiler resolution: `research-compiler-resolution.md` S3.6 (router actor default image)
- Template context: `research-compiler-resolution.md` S3.9 (TemplateContext dataclass)

### Open Questions

1. Should there be a separate template for ConfigMap-mount actors, or reuse the router template?
2. How to handle imports between ConfigMap-mounted files? (e.g., handler imports a utility from another ConfigMap-mounted file)
3. Should `asya compile` warn when a handler file grows beyond a threshold (e.g., >50KB) suggesting migration to a proper image?
4. Can we detect pip imports in the handler file (via AST analysis of `import` statements) and warn if they're not available in `router_image`?
