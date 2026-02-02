# Fix PR E2E Tests

You are tasked with fixing E2E test failures in a GitHub PR using an optimized workflow.

## Workflow

### 1. Get PR Context (30 seconds max)
```bash
# If PR number provided as argument, use it. Otherwise detect from current branch
gh pr view <PR_NUMBER> --json number,headRefName,url

# Get ONLY failed job logs (not all logs)
gh run list --branch <BRANCH> --limit 1 --json databaseId,status,conclusion
gh run view <RUN_ID> --log-failed  # Only failed job logs
```

**CRITICAL**: Read ONLY the failed test output. Skip successful jobs entirely.

### 2. Identify Problem (1 minute max)
- Search logs for: `FAILED`, `ERROR`, `AssertionError`, `Traceback`
- Extract: Test name, error message, relevant stack trace (5-10 lines max)
- Identify root cause category:
  - Test assertion failure
  - Timeout/timing issue
  - Resource not ready (pod, service, deployment)
  - Configuration error
  - Image/version mismatch

### 3. Create Worktree (15 seconds)
```bash
# Use /tmp for isolation (auto-cleanup on reboot)
WORKTREE_PATH="/tmp/fix-pr-e2e-<PR_NUMBER>"
git fetch origin
git worktree add "$WORKTREE_PATH" <BRANCH_NAME>
cd "$WORKTREE_PATH"
```

### 4. Fix the Issue (5-10 minutes)
- Make MINIMAL changes to fix the specific failure
- Do NOT refactor unrelated code
- Do NOT add extra features
- Focus on the exact error identified in step 2

**Common E2E fixes**:
- Increase timeout values in test assertions
- Add retry logic for flaky resource checks
- Fix image tags or version mismatches
- Update test expectations to match actual behavior
- Fix queue names, environment variables

### 5. Validate (optional, if fast)
If fix is simple (config change, timeout increase), skip validation.
If fix is complex (code logic), run:
```bash
make test-unit  # Only if you changed core logic
# Do NOT run full E2E locally (takes 15-25 min)
```

### 6. Commit and Push (30 seconds)
```bash
git add <CHANGED_FILES>
git commit -m "fix(e2e): <brief description of fix>

Fixes <test_name> failure caused by <root_cause>
"
git push origin <BRANCH_NAME>
```

### 7. Cleanup Worktree (10 seconds)
```bash
cd -  # Return to main repo
git worktree remove "$WORKTREE_PATH" --force
```

### 8. Report (5 seconds)
Output ONLY:
```
PR: <URL>
Fix: <one-line summary>
```

## Optimization Rules

**DO**:
- Use `gh run view --log-failed` (not `--log`)
- Read only last 50 lines of failed test output
- Use worktree in /tmp (fast, auto-cleanup)
- Make targeted fixes (change 1-3 files max)
- Push immediately after fix

**DON'T**:
- Read all CI logs (only failed jobs)
- Run full E2E tests locally (wait for CI)
- Refactor unrelated code
- Wait for CI results (report PR URL and exit)
- Keep worktree around (always cleanup)

## Expected Time Budget
- CI log analysis: 1-2 minutes
- Problem identification: 1 minute
- Fix implementation: 5-10 minutes
- Push + cleanup: 1 minute
**Total: ~10 minutes max**

## Arguments
- `<PR_NUMBER>`: PR number (optional, auto-detect from current branch if omitted)

## Example Output
```
PR: https://github.com/asya-ai/asya/pull/123
Fix: Increased pod ready timeout from 30s to 60s
```
