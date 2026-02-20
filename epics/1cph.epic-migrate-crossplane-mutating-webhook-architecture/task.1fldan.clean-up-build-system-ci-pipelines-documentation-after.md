---
title: "Clean up build system, CI pipelines, and documentation after operator removal"
status: open
priority: 3 # low
type: task
dependencies:
  - 1cph/1fdm35
---



Clean up all references to the old asya-operator after its code and Helm chart have been deleted.

## Tasks

1. **Root Makefile**: Remove operator build/test/lint targets
2. **Docker builds**: Remove operator Dockerfile and image build from CI
3. **CI pipelines** (`.github/workflows/`): Remove operator-specific jobs, update test matrix
4. **AGENTS.md / CLAUDE.md**: Remove operator references, update component overview and architecture descriptions
5. **docs/**: Update architecture docs, remove operator-specific documentation
6. **testing/**: Remove `testing/integration/operator/` test suite and fixtures
7. **Pre-commit / linting**: Remove operator paths from linter configs if referenced
8. **Symlinks**: Clean up `src/asya-operator/internal/controller/runtime_symlink/` reference in AGENTS.md

## Acceptance Criteria

- `make build`, `make test`, `make lint` all pass without operator
- CI pipeline runs successfully
- No dangling references to `asya-operator` in codebase (except git history)
- Documentation accurately reflects Crossplane-based architecture

## Technical Notes

- Run `grep -r 'asya-operator' --include='*.go' --include='*.py' --include='*.yaml' --include='*.yml' --include='*.md' --include='Makefile'` to find all references
- Some references in docs/rfc/ may be kept for historical context
- Testing infrastructure in testing/shared/ may reference operator — check compose files


---
_Migrated from beads `asya-6x5`_
