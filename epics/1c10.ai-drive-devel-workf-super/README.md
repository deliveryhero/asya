---
title: "AI-Driven Development Workflow: Superpowers + Parallel Worktrees"
status: wont_do
priority: 2 # medium
type: epic
---

Implemented with git-aint

# AI-Driven Development Workflow with Superpowers & Parallel Worktrees

## Goal
Enable AI agents to work in parallel on independent tasks using:
- **Beads** for task/issue tracking (source of truth)
- **Superpowers** for structured workflow (planning, debugging, code review)
- **Git worktrees** (via superpowers:using-git-worktrees) for isolated work
- **Parallel subagents** (Task tool with subagent_type) for concurrent execution
- **PR-based CI** for remote testing (component/integration/e2e)

## Workflow: Pick → Plan → Parallelize → Iterate

### Phase 1: Pick Work from Beads
```bash
bd ready              # Find unblocked work
bd show <id>          # Review task details
bd update <id> --status=in_progress  # Claim it
```

### Phase 2: Plan with Superpowers
Use `/superpowers:writing-plans` or `superpowers:brainstorming` to:
- Explore codebase and understand context
- Design implementation approach
- Document plan in issue description
- Mark issue as "ready to be done" (add label/note)

**Deliverable**: Markdown plan added to issue

### Phase 3: Parallelize with Subagents
Spawn independent agents in separate worktrees:
```
Main session:
  ├─ Task 1: Review & brainstorm (this session, beads + superpowers)
  │
  ├─ Subagent A (worktree-A): Implement & test locally
  │  └─ Fix based on CI failures via gh CLI
  │
  ├─ Subagent B (worktree-B): Different task simultaneously
  │  └─ Independent work, no conflicts
  │
  └─ Each subagent creates PR → CI tests remotely
```

### Phase 4: Iterate on CI Failures
Subagent reads PR logs via `gh pr view <number>` and `gh api`:
- Check test failures
- Fix code locally
- Push new commit (CI reruns automatically)
- Repeat until all tests pass
- Merge to main when ready

## Key Rules

1. **One beads issue = One atomic unit of work**
   - Clear acceptance criteria
   - Single PR per issue (usually)
   - No "I'll also fix X while here" without opening new issue

2. **Plan before code**
   - Use superpowers to understand approach
   - Document in issue description
   - Get alignment before spawning subagent

3. **Parallel work isolation**
   - Each subagent gets dedicated worktree
   - No shared branch conflicts
   - Git worktrees auto-cleanup on success

4. **CI is the system of record for testing**
   - Subagent runs unit tests locally (fast feedback)
   - PR triggers component/integration/e2e remotely
   - Subagent uses gh CLI to iterate on failures

5. **Session completion**
   - All PRs merged before session end
   - `bd close` all completed issues
   - `bd sync --from-main` to reconcile
   - `git push` to remote (MANDATORY)

## Related Tasks
- asya-4q2: Developer onboarding (CONTRIBUTING.md)
- asya-pgj: AGENTS.md enhancements for agent comprehension
- asya-jeb: Makefile targets for common workflows
- asya-p8i: .claude/settings.local.json.example
- asya-tzr: .editorconfig for editor consistency
- asya-by5: .vscode configuration
- asya-8ak: Architecture Decision Records (ADRs)

## Why This Approach?
- ✅ Beads provides persistent task tracking across sessions
- ✅ Superpowers enforce structured workflows (no ad-hoc coding)
- ✅ Parallel worktrees let agents work independently without git conflicts
- ✅ PR + CI provides remote testing (component/integration/e2e not local)
- ✅ gh CLI enables CI-integrated iteration (read logs, push fixes, repeat)
- ✅ Simple, disciplined, scales to many concurrent agents


---
_Migrated from beads `asya-214`_
