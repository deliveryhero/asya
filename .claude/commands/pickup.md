---
description: Pick up an aint (create worktree + branch, set active)
argument-hint: "<reference>"
---

Pick up an aint for active work. Creates a git worktree and branch,
and sets status to `active`. This is a shell alias that automates the
worktree setup workflow.

## Usage

```bash
git aint pickup <REFERENCE>
```

## What it does

1. Creates branch `<dir>/<id>.<slug>` (e.g. `ci-setup/c9x8.fix-auth`)
2. Creates worktree in `.worktrees/` (configurable via `git config aint.worktree-dir`)
3. Tags the aint with `worktree:<worktree-path>` and `branch:<branch>`
4. Sets status to `active`

## Examples

```bash
git aint pickup c9x8            # create worktree and start working
```

After pickup, work in the worktree directory at `.worktrees/ci-setup/c9x8.fix-auth`.
When finished, close with `git aint update c9x8 --status merged`.
