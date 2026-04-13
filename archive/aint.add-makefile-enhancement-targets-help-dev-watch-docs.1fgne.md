---
title: Add Makefile enhancement targets (help, dev, watch, docs-watch)
status: merged
priority: 2
parent: 00000
---

# Add Makefile Enhancement Targets

## Goal
Add helpful Makefile targets that improve developer experience and discoverability: `make help`, `make dev`, `make watch`, and `make docs-watch`.

## Implementation Plan

### 1. `make help` - Show all targets with descriptions

Add target that lists all Makefile targets with brief descriptions. Shows all targets, organized by category.

**Implementation**:
- Extract target names using grep/sed
- Pull comment lines (lines starting with ##) above each target
- Display in two-column format: `TARGET    Description`

**Example output**:
```
Asya 🎭 Framework - Available Targets

Build:
  build              Build all components (Go + Python)
  build-go           Build Go components only
  build-images       Build Docker images
  build-python       Build Python components only

Testing:
  test               Run all tests (unit + integration)
  test-unit          Run unit tests only (fast)
  test-component     Run component tests (Go + Python)
  test-integration   Run integration tests (multi-component)
  test-e2e           Run E2E tests in Kind cluster
  cov                Run all tests with coverage report

Code Quality:
  lint               Run linters with auto-fix enabled
  fmt                Format code (shorthand for lint)
  clean              Clean build artifacts
  clean-integration  Clean Docker Compose containers
  clean-e2e          Clean Kind cluster
  help               Show this message
```

### 2. `make dev` - One-command local dev setup

**Implementation**:
```makefile
.PHONY: dev
dev: setup  ## One-command dev environment setup
	@echo "[+] Dev environment ready!"
	@echo "Next steps:"
	@echo "  - Start coding: pick task with 'bd ready'"
	@echo "  - Run tests: make test-unit or make test"
	@echo "  - Format code: make lint"
	@echo ""
```

Just an alias for `make setup` but provides friendly messaging.

### 3. `make watch` - Re-run tests on file changes

Monitor source files and re-run unit tests automatically when changes detected.

**Implementation**:
- Use `entr` or `watchmedo` (Python fsmonitor)
- Watch `src/` directory for .go and .py changes
- Run `make test-unit` on each change
- Provide clear output on each run

**Example command**:
```bash
find src -name "*.go" -o -name "*.py" | entr -c make test-unit
```

**Implementation in Makefile**:
```makefile
.PHONY: watch
watch:  ## Watch source files and re-run unit tests on changes
	@command -v entr >/dev/null 2>&1 || { echo "entr not installed. Install with: brew install entr"; exit 1; }
	find src -type f \( -name "*.go" -o -name "*.py" \) | entr -c make test-unit
```

### 4. `make docs-watch` - Watch docs and auto-rebuild

Monitor documentation files and rebuild/reload docs automatically.

**Implementation**:
- Depends on docs tooling (mkdocs, sphinx, or custom build)
- Watch `docs/` directory for .md changes
- Rebuild docs automatically
- Optionally serve with auto-reload (if using mkdocs)

**Example (if using mkdocs)**:
```makefile
.PHONY: docs-watch
docs-watch:  ## Watch docs and auto-rebuild on changes
	@command -v mkdocs >/dev/null 2>&1 || { echo "mkdocs not installed. Install with: pip install mkdocs"; exit 1; }
	mkdocs serve
```

### 5. Integration Points

Add targets to help discovery:
- Top-level `.PHONY` declarations
- Consistent formatting (2-space indent)
- `## Comment` format for descriptions (used by `make help`)
- Alphabetical ordering within categories

### 6. Acceptance Criteria
✓ `make help` displays all targets with descriptions
✓ `make dev` provides friendly setup message
✓ `make watch` auto-runs tests on source changes (entr required)
✓ `make docs-watch` auto-rebuilds docs (depends on docs tool)
✓ All targets tested locally: make help, make watch, etc.
✓ Consistent formatting and styling
✓ No breaking changes to existing targets

## Ready to be done
Marked ready when all 4 targets are implemented and tested.


---
_Migrated from beads `asya-jeb`_
