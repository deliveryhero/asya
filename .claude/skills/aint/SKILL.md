---
name: aint
description: >
  AI-friendly issue tracker using markdown files and git. Use for multi-session
  work tracking, dependency management, and persistent context across conversation
  compaction.
allowed-tools: "Read,Bash(git aint:*)"
version: "0.1.0"
author: "atemate <https://github.com/atemate/git-aint>"
license: "Apache-2.0"
---

# git-aint - Markdown-Based Issue Tracking for AI Agents

File-based issue tracker where aints (issues) are markdown files with YAML
frontmatter, synced via git. No databases — just files and git.

**The source of truth is the files in `.aint/`** (a git worktree on the
`aint-sync` branch). You can freely read, edit, or create aint files directly.
After manual changes, run `git aint sync` to commit/push, or `git aint doctor`
to validate. The CLI commands auto-sync on every write.

## aint vs TodoWrite

| aint (persistent) | TodoWrite (ephemeral) |
|--------------------|-----------------------|
| Multi-session work | Single-session tasks |
| Complex dependencies | Linear execution |
| Survives compaction | Conversation-scoped |
| Git-backed, team sync | Local to session |

**Decision test**: "Will I need this context tomorrow?" → YES = aint

## Prerequisites

```bash
git-aint --version  # Requires git-aint installed
```

- **git-aint CLI** installed and in PATH
- **Git repository** with `git aint init` run once (humans do this, not agents)

## Session Protocol

1. `git aint list` — see open aints
2. `git aint pickup <ref>` — create worktree + branch, set status to active
3. Work in the worktree at `.worktrees/ci-setup/c9x8.fix-auth`
4. `git aint update <ref> --status merged` — mark complete

## Key Concepts

- **Aints**: markdown files in `.aint/aints/` with YAML frontmatter.
  File naming: `<status>.<id>.<slug>.md` (e.g. `active.c9x8.fix-auth.md`).
- **Directories**: grouping folders (e.g. `ci-setup/`) with `summary.md`.
  No IDs, no status — open by location, closed when moved to `.closed/`.
- **References**: bare 4-char base-36 IDs (e.g. `c9x8`) or file paths (e.g. `.aint/aints/ci-setup/active.c9x8.fix-auth.md`).
- **Statuses**: `backlog` → `open` → `active` → `pushed` → `merged` (or `rejected`).
- **Priority**: 0 critical, 1 high, 2 medium, 3 low, 4 backlog.

## Essential Commands

```bash
git aint create --title "Fix bug" --in ci-setup    # create aint
git aint get c9x8                                   # show details
git aint pickup c9x8                                # worktree + active
git aint update c9x8 --status pushed                # update status
```

Run `git aint <command> --help` for full syntax. Use `--output json` for structured output.

## Resources

| Resource | Content |
|----------|---------|
| [CLI_REFERENCE.md](resources/CLI_REFERENCE.md) | Complete command syntax |
| [WORKFLOWS.md](resources/WORKFLOWS.md) | Step-by-step workflow guides |
| [PATTERNS.md](resources/PATTERNS.md) | Common usage patterns |
| [WORKTREES.md](resources/WORKTREES.md) | Worktree development patterns |
