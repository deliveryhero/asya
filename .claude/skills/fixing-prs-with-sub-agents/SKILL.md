---
name: fixing-prs-with-sub-agents
description: Use when fixing one or multiple failing PRs by dispatching one or parallel Haiku sub-agents to create (or checkout to) git worktrees, apply fixes, and push changes - agents run unit tests only, full suite testing happens on remote CI
---

# Fixing PRs with Parallel Sub-Agents

## Overview

This skill enables systematic parallel fixing of multiple failing PRs using Haiku sub-agents. Each agent works in isolation (git worktree), applies targeted fixes, and pushes to the PR branch for remote CI validation.

**Core principle:** Sub-agents handle fixes → Remote CI validates → Loop until all tests pass.
git
**Announce at start:** "I'm using the fixing-prs-with-sub-agents skill to dispatch parallel fix agents for these PRs."

**Worktree skill:** Sub-agents should use the `using-git-worktrees` skill for isolation.

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
  1. Use the using-git-worktrees skill to create isolated workspace:
     Skill(skill="using-git-worktrees")

     When prompted for branch name, use: [actual-branch-name]
     (Get it with: gh pr view NNN --json headRefName)

  2. In the worktree directory:
     - Merge fresh main: git pull origin main
     - Apply fix: [specific changes needed]
     - Run unit tests only: make test-unit
     - If tests pass:
       * git add [files]
       * git commit -m "fix: [description]"
       * git push origin HEAD:[branch-name]

  3. Clean up:
     - Exit worktree directory
     - Skill will handle cleanup

  Report: Summary of changes + test results

  IMPORTANT:
  - Do NOT run integration/component/e2e tests
  - Only run: make test-unit
  - Push changes to remote for CI to run full suite
  - Use using-git-worktrees skill for isolation (don't manually create /tmp/ dirs)
  """
)
```

## Agent Instructions for Sub-Agents

When creating a fix agent, include these requirements:

### 1. Worktree Setup Using Skill

**Use the `using-git-worktrees` skill** for proper isolation:

```
Skill(skill="using-git-worktrees")
```

The skill will:
- Detect optimal worktree location (.worktrees/ or ~/.config/superpowers/worktrees/)
- Create isolated workspace
- Verify git safety (.gitignore checks)
- Return workspace directory path

**When prompted for branch name**, provide the actual PR branch:
```bash
# Get the PR branch name with:
gh pr view NNN --json headRefName
# Example: dependabot/go_modules/src/asya-operator/github.com/expr-lang/expr-1.17.7
```

**Verify correct branch in worktree**:
```bash
git branch -v
git log --oneline -3
```

**Why critical:** Each PR has a specific branch (often `dependabot/...`). Using the skill ensures proper isolation and safety checks.

### 2. Merge Fresh Main

```bash
git pull origin main  # Merge latest from main
```

**Why needed:** Ensures fixes are compatible with current main code.

### 3. Apply Fix

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

**Critical:** Push to the ACTUAL PR branch, not to main or whatever other branch.

Get branch name with:
```bash
git branch -v  # Shows current branch
# or
gh pr view NNN --json headRefName
```

### 6. Clean Up

The `using-git-worktrees` skill handles all cleanup automatically:
- Removes worktree after agent completes
- Cleans up branch references
- Verifies cleanup was successful

No manual cleanup needed.

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

Typically, it takes ~5 minutes to run integration tests and ~20 minutes for e2e tests.

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


## Safety Rules

1. **Always use `using-git-worktrees` skill** - Creates proper isolation, verifies safety
2. **Run unit tests first** - Before pushing
3. **Push to PR branch** - Not to main or rfc0 (use `gh pr view NNN --json headRefName`)
4. **Let skill handle cleanup** - Don't manually remove worktrees
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


## Troubleshooting

### Unit Tests Pass but E2E Tests Fail on Remote

**Expected:** This is normal - E2E tests need full Kind cluster

**Next:** Analyze E2E logs and create new fix agent with specific error details

## Example: Complete PR Fix Workflow

```bash
# 1. Create umbrella (if needed)
bd create --title="[Umbrella] Fix expr 1.17.7 upgrade issues" --type=epic --priority=1
# → Returns: asya-abc

# 2. Analyze (optional, if not already known)
Task(
  description="Analyze PR #74 failure",
  subagent_type="general-purpose",
  model="haiku",
  prompt="Analyze PR #74 failure using gh CLI: ..."
)

# 3. Dispatch fix agents IN PARALLEL (5 agents at once)
Task 1: Fix PR #74 using using-git-worktrees skill
Task 2: Fix PR #78 using using-git-worktrees skill
Task 3: Fix PR #89 using using-git-worktrees skill
Task 4: Fix PR #91 using using-git-worktrees skill
Task 5: Fix PR #92 using using-git-worktrees skill

# Each agent will:
# - Call Skill(skill="using-git-worktrees")
# - Apply fix in isolated workspace
# - Run make test-unit
# - Push to PR branch
# - Let skill cleanup

# 4. Monitor results (check every 5 minutes)
for pr in 74 78 89 91 92; do
  gh pr view $pr --json statusCheckRollup
done

# 5. If failures, create new fix agents
Task: Re-fix PR #XX using using-git-worktrees skill
  Prompt: "Previous fix showed [error]. New root cause: [analysis]. Apply this fix instead: ..."
```

## Key Decisions

- **Model**: Always use Haiku for fix agents (lightweight, cost-effective)
- **Testing**: Unit tests locally, full suite on remote CI
- **Parallelism**: Launch all fix agents simultaneously
- **Isolation**: Each agent gets own worktree, prevents conflicts
- **Tracking**: Use beads to track progress
