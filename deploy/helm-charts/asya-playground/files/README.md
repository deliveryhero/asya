# Helm Chart Files

This directory contains non-template files that are embedded into the Helm chart
using `.Files.Get`. These are typically configuration files, dashboards, or other
assets that need to be included in Kubernetes resources.

## Symlinked Files

Files in this directory are symlinks to their source locations to maintain a
single source of truth. The symlinks are validated by `.pre-commit-hooks/check-symlinks.sh`.

| File | Source | Purpose |
|------|--------|---------|
| `asya-actors-overview.json` | `deploy/grafana-dashboards/asya-actors-overview.json` | Grafana dashboard for Asya actor metrics |

## Adding New Files

1. Create the source file in its canonical location (e.g., `deploy/grafana-dashboards/`)
2. Create a relative symlink here: `ln -s ../../../<path-to-source> <filename>`
3. Add the mapping to `.pre-commit-hooks/check-symlinks.sh`
4. Reference in templates using `.Files.Get "files/<filename>"`
