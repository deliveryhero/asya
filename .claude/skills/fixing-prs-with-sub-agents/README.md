# Fixing PRs with Sub-Agents: Quick Reference

## Pattern Overview

This skill implements a systematic approach to fixing multiple failing PRs:

1. **Parallel agents** (Haiku model) work on each PR independently
2. **Isolated worktrees** prevent conflicts and allow concurrent work
3. **Unit tests locally**, full suite runs on remote CI
4. **Push to PR branches** for remote validation
5. **Iterate** based on CI results

## Quick Start

```bash
# 1. Check failing PRs
gh pr list --state open

# 2. Read the skill
cat .claude/skills/fixing-prs-with-sub-agents/SKILL.md

# 3. Dispatch fix agents in parallel using Task tool
Task(
  description="Fix PR #NNN: [issue]",
  subagent_type="general-purpose",
  model="haiku",
  prompt="[Instructions from SKILL.md]"
)
```

## Key Rules (Enforce These!)

### Git Worktree Pattern
```bash
git worktree add /tmp/fix-pr-NNN origin/[branch-name]
cd /tmp/fix-pr-NNN
git pull origin main                    # Merge fresh main
[apply fix]
make test-unit                          # ONLY unit tests!
git commit -m "fix: [description]"
git push origin HEAD:[branch-name]
cd /home/a.yushkovskiy/asya
git worktree remove /tmp/fix-pr-NNN
```

### Critical Constraints

- ❌ **Don't run**: `make test-component`, `make test-integration`, `make test-e2e`
- ✅ **Only run**: `make test-unit`
- ❌ **Don't push to**: `main`, `rfc0`
- ✅ **Always push to**: The actual PR branch (get it with `gh pr view NNN --json headRefName`)
- ❌ **Don't merge main** unless necessary
- ✅ **Always cleanup** worktrees after pushing

### Testing Strategy

```
Agent's Local Machine:
  └─ Run unit tests only
     └─ If PASS → Push to remote
     └─ If FAIL → Debug, fix, retry

Remote CI (GitHub Actions):
  └─ Run full test suite
  └─ Component, integration, E2E tests
  └─ Multiple platforms if applicable
```

## Common Fix Patterns

### Pattern 1: Revert Problematic Dependency
```bash
sed -i 's/package v1.2.3/package v1.2.0/' go.mod
cd [module-dir] && go mod tidy
```

### Pattern 2: Update Configuration
```bash
sed -i 's/old_value/new_value/' config/file.yaml
```

### Pattern 3: Reduce Timeout/Interval
```bash
sed -i 's/5m/30s/' deploy/helm/values.yaml
```

## Monitoring Results

```bash
# Check single PR
gh pr view 92 --json statusCheckRollup

# Check multiple PRs
for pr in 74 78 89 91 92; do
  echo "=== PR #$pr ==="
  gh pr view $pr --json statusCheckRollup -q '.statusCheckRollup[] | select(.conclusion != null) | "\(.name): \(.conclusion)"'
done

# Watch for updates
watch -n 30 'gh pr view 92 --json statusCheckRollup'
```

## Handling Failures

When a test fails on remote CI:

1. **Get the logs**
   ```bash
   gh run view [run-id] --log -j [job-id] 2>&1 | tail -200
   ```

2. **Identify the issue**
   - Which test failed?
   - What was the error?
   - Is it related to the fix?

3. **Create new fix agent**
   ```
   Task(
     description="Fix PR #NNN: [new root cause]",
     subagent_type="general-purpose",
     model="haiku",
     prompt="Previous fix showed [error].
             New root cause: [analysis]
             Apply this fix instead: [new approach]"
   )
   ```

4. **Repeat** until tests pass

## Example: Complete Campaign

```bash
# Session start: Identify failing PRs
gh pr list --state open | grep "expr\|KEDA"

# Create umbrella tracking
bd create --title="[Umbrella] Fix expr/KEDA upgrade issues" --type=epic --priority=1
# Returns: asya-xyz

# Dispatch 5 fix agents in PARALLEL
Task 1: Fix PR #74 (expr operator)
Task 2: Fix PR #78 (expr integration)
Task 3: Fix PR #89 (KEDA integration)
Task 4: Fix PR #91 (expr component)
Task 5: Fix PR #92 (KEDA component)

# Wait for agents to complete...
# All agents push to their respective PR branches

# Monitor CI results (repeat every 5 minutes)
for pr in 74 78 89 91 92; do
  gh pr view $pr --json files -q '.files | length' | xargs echo "PR #$pr:"
done

# Check if any failed
gh pr view 92 --json statusCheckRollup -q '.statusCheckRollup[] | select(.conclusion == "FAILURE")'

# If failures, get logs and create new fix agents
# Repeat until all tests pass

# Final: Clean up
bd close asya-z8g asya-1s1 asya-a92 asya-bj3 asya-w5z asya-xyz --reason="All PRs fixed and validated on remote CI"
```

## Success Criteria

A PR fix is complete when:

✅ Unit tests pass locally
✅ Code is pushed to PR branch
✅ Remote CI completes (all checks pass)
✅ No more test failures

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| Agent pushed to wrong branch | Misidentified PR branch | Use `gh pr view NNN --json headRefName` to get correct name |
| PR shows 0 files changed | Fix reverted to match main | This is OK if revert is intentional |
| Unit tests pass but E2E fails on CI | E2E needs full environment | Normal - that's why we test remotely |
| Worktree already exists | Leftover from previous run | `git worktree remove /tmp/fix-pr-NNN` |
| go mod tidy fails | Go environment not set up | Agent should work in module directory: `cd [module] && go mod tidy` |

## When NOT to Use This Skill

❌ Single PR fix (use direct approach instead)
❌ Fixes requiring new feature implementation (use proper feature branch workflow)
❌ Changes to core logic beyond simple config/dependency updates
❌ When you need to run full test suite locally (not enough resources)

## See Also

- `.claude/SETUP.md` - Project setup and tools
- `.claude/skills/fixing-prs-with-sub-agents/SKILL.md` - Full skill documentation
- `AGENTS.md` - Project architecture and guidelines
- `CONTRIBUTING.md` - Development workflow
