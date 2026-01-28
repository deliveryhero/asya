---
name: fixing-prs-with-sub-agents
description: Use when fixing multiple failing PRs by dispatching parallel Haiku sub-agents to create worktrees, apply fixes, and push changes - agents run unit tests only, full suite testing happens on remote CI
---

# Fixing PRs with Parallel Sub-Agents

## Overview

This skill enables systematic parallel fixing of multiple failing PRs using Haiku sub-agents. Each agent works in isolation (git worktree), applies targeted fixes, and pushes to the PR branch for remote CI validation.

**Core principle:** Sub-agents handle fixes → Remote CI validates → Loop until all tests pass.
git
**Announce at start:** "I'm using the fixing-prs-with-sub-agents skill to dispatch parallel fix agents for these PRs."

## Key Constraints

- **Sub-agents**: Use Haiku model (lightweight, fast)
- **Testing**: Agents run ONLY unit tests locally (`make test-unit`)
- **Integration/Component/E2E tests**: ONLY on remote CI (requires single machine)
- **Isolation**: Each agent works in separate git worktree
- **Git operations**: Use `git worktree` for branch-specific work
- **CI access**: Use `gh` CLI to check build status and fetch logs

## Workflow

### Phase 1: Investigation

1. **Identify failing PRs**
   ```bash
   gh pr list --state open --search "is:failing"
   ```

2. **Create umbrella tracking issue** (if multiple related failures)
   ```bash
   bd create --title="[Umbrella] PR Fix Campaign" --type=epic --priority=1
   ```

3. **Link all PR issues** to umbrella

### Phase 2: Parallel Analysis (Optional)

If needed, dispatch Haiku sub-agents to analyze each PR:

```
Task(
  description="Analyze PR #NNN failure",
  subagent_type="general-purpose",
  model="haiku",
  prompt="""
  Analyze PR #NNN using gh CLI:
  1. gh pr view NNN --json statusCheckRollup,title
  2. Identify which tests failed
  3. Get build logs from failed job
  4. Identify root cause
  5. Return: test name, error type, root cause
  """
)
```

### Phase 3: Dispatch Fix Agents

Launch Haiku sub-agents IN PARALLEL for each PR:

```
Task(
  description="Fix PR #NNN: [issue description]",
  subagent_type="general-purpose",
  model="haiku",
  prompt="""
  Fix PR #NNN in isolated git worktree.

  ROOT CAUSE: [identified issue]

  STEPS:
  1. Create worktree: git worktree add /tmp/fix-pr-NNN origin/[branch-name]
  2. cd /tmp/fix-pr-NNN
  3. Merge fresh main: git pull origin main
  4. Apply fix: [specific changes needed]
  5. Run unit tests only: make test-unit
  6. If tests pass:
     - git add [files]
     - git commit -m "fix: [description]"
     - git push origin HEAD:[branch-name]
  7. Clean up: cd /home/a.yushkovskiy/asya && git worktree remove /tmp/fix-pr-NNN

  Report: Summary of changes + test results

  IMPORTANT:
  - Do NOT run integration/component/e2e tests
  - Only run: make test-unit
  - Push changes to remote for CI to run full suite
  """
)
```

## Agent Instructions for Sub-Agents

When creating a fix agent, include these requirements:

### 1. Worktree Setup

```bash
# Create isolated workspace
git worktree add /tmp/fix-pr-NNN origin/[actual-branch-name]
cd /tmp/fix-pr-NNN

# Verify on correct branch
git branch -v
git log --oneline -3
```

**Why critical:** Each PR has a specific branch (often `dependabot/...`). Use `gh pr view NNN --json headRefName` to get the exact branch name.

### 2. Merge Fresh Main

```bash
git pull origin main  # Merge latest from main
```

**Why needed:** Ensures fixes are compatible with current main code.

### 3. Apply Fix

The fix strategy depends on root cause:

**Version incompatibility (revert to known-good):**
```bash
# Example: expr 1.17.7 → 1.17.0
sed -i 's/expr v1.17.7/expr v1.17.0/' go.mod
go mod tidy
```

**Configuration workaround:**
```bash
# Example: reduce health check interval
sed -i 's/5m/30s/' config/values.yaml
```

**Code change (small fix):**
```bash
# Edit file with targeted changes
# Minimal modifications only
```

### 4. Unit Tests Only

```bash
# Run ONLY unit tests
make test-unit

# Do NOT run:
# - make test-component
# - make test-integration
# - make test-e2e
```

**Why restricted:** Component/integration/E2E tests require full environment setup (Docker, Kind cluster). Only one agent/human should run these per machine to avoid resource contention.

### 5. Push to Remote

If unit tests pass:

```bash
git add [specific files]
git commit -m "fix: [description]"
git push origin HEAD:[branch-name]
```

**Critical:** Push to the ACTUAL PR branch, not to rfc0 or main.

Get branch name with:
```bash
git branch -v  # Shows current branch
# or
gh pr view NNN --json headRefName
```

### 6. Clean Up

```bash
cd /home/a.yushkovskiy/asya
git worktree remove /tmp/fix-pr-NNN
```

## Phase 4: Monitor Remote CI

After all agents push, monitor build results:

```bash
# Check all PR statuses
for pr in 74 78 89 91 92; do
  gh pr view $pr --json statusCheckRollup,state
done

# Get logs for failed test
gh run view [run-id] --log -j [job-id] 2>&1 | tail -100
```

## Phase 5: Iterative Loop

If tests still fail on remote CI:

1. **Analyze failure**: Get logs via `gh` CLI
2. **Identify issue**: Which test failed, what was the error
3. **Create new fix**: Launch another sub-agent with root cause details
4. **Repeat**: Until all tests pass

## Common Patterns

### Pattern: Revert Problematic Dependency

```bash
# Find current version
grep "package-name" go.mod

# Change to known-good version
sed -i 's/package-name v1.2.3/package-name v1.2.0/' go.mod
go mod tidy
```

### Pattern: Reduce Health Check Timeout

```bash
# For E2E tests
sed -i 's/HEALTH_CHECK_INTERVAL=5m/HEALTH_CHECK_INTERVAL=30s/' deploy/helm/values.yaml
```

### Pattern: Fix Configuration

```bash
# Update test configuration
cat > testing/config.yaml << EOF
timeout: 120
interval: 30s
EOF
```

## Safety Rules

1. **Always use git worktree** - Never modify main workspace
2. **Run unit tests first** - Before pushing
3. **Push to PR branch** - Not to main or rfc0
4. **Clean up worktrees** - After pushing
5. **Report clearly** - Summary of changes and test results
6. **No merges without tests** - Must pass at least unit tests locally

## Expected Output from Agents

Each sub-agent should report:

```
Summary:

PR #NNN: [Title]
Root Cause: [Issue]
Files Changed: [list]
Unit Tests: [PASSED/FAILED]
Status: [Pushed to remote OR Failed tests]

Changes:
- [file]: [change description]
- [file]: [change description]

Next: Waiting for remote CI build results
```

## Monitoring Build Results

After fixes are pushed, watch for CI updates:

```bash
# Watch single PR
gh pr view 92 --json statusCheckRollup -q '.statusCheckRollup[] | select(.name == "Unit tests") | {name, conclusion}'

# Watch all PRs
watch -n 30 'for pr in 74 78 89 91 92; do echo "PR #$pr:"; gh pr view $pr --json statusCheckRollup -q ".statusCheckRollup[] | select(.conclusion != null) | .name, .conclusion" | head -3; done'
```

## Troubleshooting

### Agent Pushes to Wrong Branch

**Problem:** Agent pushed to `rfc0` instead of PR branch

**Solution:**
1. Get correct branch name: `gh pr view NNN --json headRefName`
2. Force-reset PR branch: `git reset --hard [commit-with-fix]`
3. Force-push: `git push -f origin HEAD:[correct-branch]`

### PR Shows 0 Files Changed

**Cause:** Fix reverted changes to match main (e.g., reverted version upgrade)

**Status:** This is actually CORRECT if the fix is to avoid a problematic upgrade

**Action:** Decide if the revert is acceptable or if proper fix is needed

### Unit Tests Pass but E2E Tests Fail on Remote

**Expected:** This is normal - E2E tests need full Kind cluster

**Next:** Analyze E2E logs and create new fix agent with specific error details

## Example: Complete PR Fix Workflow

```bash
# 1. Create umbrella
bd create --title="[Umbrella] Fix expr 1.17.7 upgrade issues" --type=epic --priority=1
# → Returns: asya-abc

# 2. Analyze (optional, if not already known)
Task(subagent_type="general-purpose", model="haiku",
  prompt="Analyze PR #74 failure using gh CLI...")

# 3. Dispatch fix agents (PARALLEL)
Task 1: Fix PR #74 (expr revert)
Task 2: Fix PR #78 (expr revert)
Task 3: Fix PR #89 (KEDA downgrade)
Task 4: Fix PR #91 (health interval config)
Task 5: Fix PR #92 (health interval config)

# 4. Monitor results
for pr in 74 78 89 91 92; do
  gh pr view $pr --json statusCheckRollup
done

# 5. If failures, iterate
Task: Re-fix PR #XX based on CI logs
```

## Key Decisions

- **Model**: Always use Haiku for fix agents (lightweight, cost-effective)
- **Testing**: Unit tests locally, full suite on remote CI
- **Parallelism**: Launch all fix agents simultaneously
- **Isolation**: Each agent gets own worktree, prevents conflicts
- **Tracking**: Use beads to track progress
