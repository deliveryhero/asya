# git-aint: Agent Instructions

This project uses **git-aint** — AI Native Tracker — for intent-based issue tracking.

## How It Works

Aints are markdown files in `.aint/active/` (work in progress) and `.aint/archive/`
(completed). The `.aint/` directory is a git worktree on the `aint-sync` branch,
gitignored from the main branch.

Only aints have IDs. Supporting files (rfc.md, adr.*.md, etc.) are free-format.

## File Naming

- **Aint file:** `aint.{slug}.{id}.md` (e.g., `aint.fix-auth.ab12c.md`)
- **Aint directory:** `aint.{slug}.{id}/` with `aint.md` inside
- **Supporting files:** free-format, no IDs (e.g., `rfc.md`, `adr.nats-over-pg.md`)
- **IDs:** 5-char base-36 random (`[0-9a-z]`)
- **Slug:** human-readable, any chars except `.`

## Statuses

`open` -> `working` -> `pushed` -> `merged` | `rejected`

## Commands (8 total)

```bash
git aint init                              # setup .aint/ worktree
git aint new --title "Fix auth"            # create aint
git aint get                               # table of all aints
git aint get <id>                          # one aint (table row)
git aint get <id> -o detail                # full detail view
git aint get -o tree                       # tree view
git aint get -o files                      # filesystem tree with metadata
git aint get --with children               # include children
git aint get --with dependants             # include dependants
git aint get --with blockers               # include blockers
git aint set <id> --status working         # update status
git aint set <id> --priority 1             # update priority
git aint set <id> --add-tag "pr:123"       # add tag
git aint rm <id>                           # remove aint
git aint rm <id> --file rfc.md             # remove file from aint
git aint new <id> --file rfc.md            # add file to aint dir
git aint sync                              # pull/commit/push + regenerate auto_state.md
git aint doctor                            # validate + fix
git aint exec <id> -- <cmd>                # run command in aint worktree
```

## Compound Operations (shell script aliases)

```bash
git aint pickup <id>     # create worktree + set working
git aint reject <id>     # set rejected + reason
git aint cleanup         # remove stale worktrees/branches
git aint aliases         # list all aliases with descriptions
```

## File Structure

```
.aint/
  active/                           # work in progress
    aint.fix-auth.ab12c.md          # file-form aint
    aint.gateway-rearch.ef56g/      # directory-form aint
      aint.md                       # aint metadata
      rfc.md                        # supporting doc (free-format)
      aint.strip-pg.cd34h.md        # child aint
  archive/                          # completed aints
  docs/                             # static reference docs
  trash/                            # ephemeral scratch (plans)
  scripts/                          # shell scripts for aliases
  auto_state.md                     # auto-generated project state
  AGENTS.md                         # this file
```

## Frontmatter

```yaml
---
title: "Fix auth redirect"
status: open
priority: 2
dependencies: [zz99q]
tags:
  - pr:401
  - worktree:.worktrees/ab12c.fix-auth
  - branch:ab12c.fix-auth
---
```

## Output Formats (-o flag)

`table` (default) | `tree` | `detail` | `files` | `wide` | `json` | `yaml`

## Composition & Dependencies

- **Composition** (parent/child): expressed by filesystem nesting — child aints live inside parent directory
- **Dependencies** (ordering): expressed in frontmatter `dependencies: [id1, id2]` — cross-directory

## References

- Bare 5-char ID: `ab12c`
- All commands accept bare IDs

## Current Project State

@auto_state.md
