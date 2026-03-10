---
description: Mark aint as merged and clean up worktree, branch, tmux
argument-hint: "<reference>"
---

Mark an aint as merged and automatically clean up its worktree, branch,
and tmux session.

## Usage

```bash
git aint merge <REFERENCE> [--reason <text>] [--no-cleanup]
```

## What it does

1. Sets aint status to `merged`
2. Removes the git worktree
3. Deletes the local branch (if gone from remote)
4. Kills the tmux session (if any)

Use `--no-cleanup` to only set status without cleaning up resources.

## Examples

```bash
git aint merge c9x8                          # merge + cleanup
git aint merge c9x8 --reason "PR #42 merged" # with reason
git aint merge c9x8 --no-cleanup             # status only
```
