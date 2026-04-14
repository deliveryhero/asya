---
title: Enhance AGENTS.md with decision trees for faster agent comprehension
status: open
priority: 2
---

# Enhance AGENTS.md with Decision Trees for Agent Comprehension

## Goal
Add decision tree sections to AGENTS.md that help AI agents quickly determine which tool/action to use for common scenarios. This creates a reference guide agents can follow to make better decisions faster.

## Implementation Plan

### 1. Add Decision Trees Section to AGENTS.md
Create new section after "Key Deployment Facts":

```markdown
## Decision Trees for AI Agents

Quickly determine the right approach for common development scenarios.
```

### 2. Decision Trees to Implement

**Tree 1: Component Routing**
```
"I need to modify component behavior"
├─ Actor execution logic → src/asya-runtime/asya_runtime.py
├─ Message routing → src/asya-sidecar/ (Go)
├─ HTTP/MCP gateway → src/asya-gateway/ (Go)
├─ Kubernetes operator → src/asya-operator/ (Go)
├─ Python runtime utilities → src/asya-crew/ or src/asya-cli/
└─ Testing infrastructure → testing/{component,integration,e2e}/
```

**Tree 2: Testing Strategy**
```
"Should I run tests and which ones?"
├─ Making code change
│  ├─ Python/Go code → make test-unit (local, fast)
│  ├─ Sidecar/runtime integration → make test-component (local, ~2min)
│  ├─ Multi-component interaction → make test-integration (local, ~5min)
│  ├─ Kubernetes features (operator, KEDA) → PR triggers CI (remote, ~15min)
│  └─ Full E2E pipeline → PR triggers CI (remote, ~30min)
├─ Checking coverage → make cov (combines all tests + reports)
├─ Before creating PR → make test (unit + integration)
└─ Local E2E testing → DON'T (Kind is single-user, use PR/CI)
```

**Tree 3: Error Recovery**
```
"Tests are failing, what do I do?"
├─ Unit test fails
│  ├─ Read error message
│  ├─ Fix code locally
│  ├─ Rerun: make test-unit -C src/{component}/
│  └─ Repeat until passing
├─ Component/Integration test fails
│  ├─ Check Docker containers: docker ps
│  ├─ Read test logs: docker logs {container}
│  ├─ Fix code or test infrastructure
│  ├─ Cleanup: make clean-integration
│  ├─ Rerun: make test-integration
│  └─ Repeat until passing
├─ PR test fails (from gh CLI)
│  ├─ Read test logs: gh run view {run_id} --log
│  ├─ Or list failed checks: gh pr checks {pr_number}
│  ├─ Fix code locally
│  ├─ Commit and push (CI reruns automatically)
│  └─ Repeat until all checks pass
└─ Linter fails
│  ├─ Auto-fix: make lint (fixes formatting)
│  ├─ If still failing → manual fix required (security/type checks)
│  └─ See "Linting" section in AGENTS.md
```

**Tree 4: Git Workflow**
```
"I'm done with my task, what next?"
├─ Verify work
│  ├─ Local tests pass: make test
│  ├─ Code follows style: make lint
│  ├─ No stray files: git status
│  └─ All changes intentional: git diff
├─ Complete beads task
│  ├─ bd close {id} "Completed: {summary}"
│  ├─ bd sync --from-main
│  └─ git add . && git commit
├─ Create PR (if not already created)
│  ├─ Push to remote
│  ├─ gh pr create {body}
│  └─ Wait for CI checks
├─ Handle CI failures
│  ├─ gh pr view {number} (see status)
│  ├─ Fix code locally
│  ├─ Push new commit (CI reruns)
│  └─ Repeat until passing
└─ Merge when ready
   ├─ All CI checks pass
   ├─ Code review approved (if applicable)
   ├─ gh pr merge {number}
   └─ Session complete: git push && verify "up to date"
```

**Tree 5: Worktree Management**
```
"I'm starting new work, how do I avoid conflicts?"
├─ Main session
│  ├─ Use superpowers:using-git-worktrees
│  ├─ Create worktree for isolated work
│  └─ Spawn subagent in that worktree
├─ Subagent session
│  ├─ Works in isolated directory
│  ├─ Can commit/test without affecting main
│  ├─ Creates PR from that branch
│  └─ Auto-cleanup on completion
└─ Result
   └─ No git conflicts, parallel work possible
```

**Tree 6: Blocked or Uncertain?**
```
"I'm unsure what to do or blocked"
├─ Research needed
│  ├─ Explore codebase: Task tool with Explore agent
│  ├─ Search files: Grep/Glob tools
│  └─ Read architecture docs: docs/architecture/
├─ Planning needed
│  ├─ Use superpowers:brainstorming
│  ├─ Use superpowers:writing-plans
│  └─ Document approach in beads issue
├─ Code review needed
│  ├─ Use superpowers:requesting-code-review
│  ├─ Share PR URL with reviewer
│  └─ Iterate on feedback
└─ Task dependency
   ├─ Identify blocking issue: bd blocked
   ├─ Create dependency: bd dep add {task} {blocking-task}
   └─ Work on other unblocked tasks first
```

### 3. Formatting
- Use clear indentation (├─, └─) for tree structure
- Include code blocks for example commands
- Link to relevant AGENTS.md sections
- Add brief explanation after each leaf node

### 4. Acceptance Criteria
✓ At least 6 decision trees covering common scenarios
✓ Clear if-then structure with proper indentation
✓ Markdown renders correctly in GitHub
✓ Links to relevant sections in AGENTS.md
✓ Real examples from codebase workflows
✓ Passes linter (make lint)

## Ready to be done
Marked ready when all decision trees are added and formatted.


_Migrated from beads `asya-pgj`_
