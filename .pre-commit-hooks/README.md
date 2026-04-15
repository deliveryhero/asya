# Pre-commit Hook Scripts

Custom scripts for enforcing repository-specific rules.

## check-symlinks.sh

Ensures critical files remain as symlinks to prevent duplicate content.

### Checked Symlinks

- **`asya_runtime.py`**: The Python runtime script must be symlinked (not copied)
  - Source: `src/asya-runtime/asya_runtime.py`
  - Symlink: `deploy/helm-charts/asya-crossplane/files/asya_runtime.py`

## check-chart-locks.sh

Validates that `Chart.lock` files do not contain `file://` dependencies. This prevents
accidentally committing locks generated from `Chart.yaml.local` (the local-dev variant
that uses `file://` paths for unpublished chart changes).

## compile-flows.sh

Compiles all example and test flow definitions in parallel, verifying they produce valid
manifests and graph PNGs. Key behaviors:

- **Collision detection**: fails fast if two flow files define a `@flow` function with
  the same name (would write to the same output directory)
- **Pinned Graphviz**: builds a Docker image (`asya-graphviz:12.2.0`) from
  `Dockerfile.graphviz` for reproducible PNG rendering; falls back to local `dot`
- **PYTHONPATH**: adds `examples/flows/` so shared helpers (e.g. `_asya_utils`) are
  importable

## Why This Matters

- **Symlinks** ensure single source of truth for files used in multiple locations
- **Relative symlinks** work across different machines/git clones (unlike absolute paths)
- **Chart.lock validation** catches local-only dependencies before they reach CI
- **Flow compilation** catches broken flow definitions and graph rendering issues early
- Pre-commit hooks prevent accidentally committing invalid state
