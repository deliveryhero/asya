---
title: Create developer onboarding guide (CONTRIBUTING.md)
status: open
priority: 2 # medium
type: task
---


# Developer Onboarding Guide (CONTRIBUTING.md)

## Goal
Create comprehensive CONTRIBUTING.md that explains the AI-driven development workflow, setup, and common tasks for developers and AI agents.

## Implementation Plan

### 1. Structure
```
CONTRIBUTING.md
├── Quick Start
│   ├── One-command setup: make setup
│   ├── Verify setup: make test
│   └── Run linters: make lint
├── Understanding the Workflow
│   ├── Beads for task tracking
│   ├── Superpowers for structured work
│   ├── Parallel agents with worktrees
│   └── PR-based CI testing
├── Development Workflows
│   ├── Picking a task: bd ready → bd show → bd update
│   ├── Planning with superpowers
│   ├── Implementing with subagents
│   ├── Iterating on CI failures
│   └── Landing the plane (session completion)
├── Testing Workflows
│   ├── Local unit tests: make test-unit
│   ├── Component tests: make test-component
│   ├── Integration tests: make test-integration
│   ├── E2E tests: PR triggers CI (don't run locally)
│   └── Coverage: make cov
├── Common Tasks
│   ├── Adding a new feature
│   ├── Fixing a bug
│   ├── Running tests before PR
│   ├── Handling CI test failures
│   └── Merging and cleanup
├── Troubleshooting
│   ├── Pre-commit hook failures
│   ├── Git worktree conflicts
│   ├── Docker Compose issues
│   ├── Kind cluster debugging
│   └── Coverage report problems
├── Resources
│   ├── AGENTS.md (AI agent guide)
│   ├── CLAUDE.md (project instructions)
│   ├── Architecture docs (docs/architecture/)
│   └── ADRs (decision records)
```

### 2. Key Sections to Write

**Quick Start**: Copy from AGENTS.md prerequisites + make setup

**Understanding the Workflow**: Summarize asya-214 epic in developer-friendly language

**Development Workflows**: Step-by-step for each common scenario
- "I want to pick up a task"
- "I'm planning my approach"
- "I'm implementing and testing"
- "My PR has test failures"
- "I'm ready to merge"

**Testing Workflows**: Link to AGENTS.md test hierarchy, explain when to use what

**Common Tasks**: Real examples from issues (e.g., "Add a new Flow DSL feature")

**Troubleshooting**: Copy from AGENTS.md + add local development issues

### 3. Acceptance Criteria
✓ CONTRIBUTING.md covers all 7 main sections
✓ Examples for local development (unit/component tests)
✓ Clear guidance on when to use PR/CI vs local testing
✓ Links to AGENTS.md and CLAUDE.md
✓ Markdown is well-formatted and readable
✓ Runs through linter without errors

## Ready to be done
Marked ready when plan is complete and documented here.


---
_Migrated from beads `asya-4q2`_
