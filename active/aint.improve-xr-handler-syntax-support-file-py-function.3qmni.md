---
title: "Improve XR handler syntax: support file.py:function format for explicit handler resolution"
status: open
priority: 2
---

## Problem

The current `spec.handler` format in AsyncActor XRDs uses Python module-dot-function notation
(e.g. `echo_handler.process`). This relies on PYTHONPATH being set correctly so that the runtime
can `import echo_handler` and then call `.process`.

This creates a mismatch between the localhost compiler's Python environment (which may have
`PYTHONPATH=.` or different package layouts) and the container's Python environment. The handler
that works locally may not resolve inside the container.

## Proposed Solution

Support an explicit file-path-based handler syntax:

\`\`\`
handler: /path/to/file.py:function_name
\`\`\`

The runtime would:
1. Detect the colon-separated format
2. Import the file at the given path using `importlib.util.spec_from_file_location`
3. Look up the function by name from the loaded module

## Corner Cases to Explore

- **Bare script** (no package): `/opt/handlers/echo.py:process` — simple file import
- **Part of a package**: `/opt/handlers/mypackage/echo.py:process` — may need package context for relative imports within the file
- **Relative imports inside the handler file**: `from .utils import helper` — won't work with `spec_from_file_location` unless package context is set up
- **Class methods**: `/opt/handlers/echo.py:MyClass.process` — need to instantiate or use classmethod
- **Nested modules**: `/opt/handlers/mypackage/submodule/echo.py:process` — deep path
- **Symlinks**: handler file is a symlink (like asya_runtime.py itself)
- **Backwards compatibility**: existing `module.function` format must continue to work
- **Docker Compose vs K8s**: in compose, files are bind-mounted at known paths; in K8s, code is baked into the image or mounted via ConfigMap

## Rule of Thumb

Handler must be a fully qualified name resolvable inside the container's Python:
- `module.function` — resolved via PYTHONPATH (current behavior)
- `/path/to/file.py:function` — resolved via filesystem (proposed)
