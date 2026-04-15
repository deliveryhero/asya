# git-aint: Agent Instructions

This project uses **git-aint** — AI Native Tracker — for intent-based issue tracking.

## How It Works

Aints are markdown files in `.aint/active/` (work in progress) and `.aint/archive/`
(completed or rejected). The `.aint/` directory is a git worktree on the `aint-sync`
branch, gitignored from the main branch.

Only aints have IDs. Supporting files (rfc.md, adr.*.md, etc.) are free-format.

## File Naming

- **Aint file:** `aint.{slug}.{id}.md` (e.g., `aint.fix-auth.ab12c.md`)
- **Aint directory:** `aint.{slug}.{id}/` with `aint.md` inside
- **Supporting files:** free-format, no IDs (e.g., `rfc.md`, `adr.nats-over-pg.md`)
- **IDs:** 5-char base-36 random (`[0-9a-z]`)
- **Slug:** human-readable, hyphens between tokens (never dots)

## Statuses

`open` -> `working` -> `pushed` -> `merged` | `rejected`

Active statuses (`open`, `working`, `pushed`) live in `active/`.
Closed statuses (`merged`, `rejected`) live in `archive/`.
Changing status moves the file automatically.

## Commands (8 total)

```bash
git aint init                              # setup .aint/ worktree (idempotent)
git aint new --title "Fix auth"            # create aint in active/
git aint new --title "Subtask" --in <id>   # create child aint
git aint get                               # table of all active aints
git aint get <id>                          # one aint (table row)
git aint get <id> -o detail                # full detail view
git aint get -o tree                       # tree view
git aint get -o files                      # filesystem tree with metadata
git aint get -s "query"                    # search titles and body
git aint get -s "query" -S                 # search with AND logic (all words must match)
git aint get --search-files "rfc.md"       # also search inside aint directory files
git aint get --with children               # include children
git aint get --with dependants             # include dependants
git aint get --with blockers               # include blockers
git aint get --status closed               # show merged + rejected
git aint get --deps clear                  # unblocked aints only
git aint set <id> --status working         # update status (moves file if needed)
git aint set <id> --priority 1             # update priority
git aint set <id> --add-tag "pr:123"       # add tag
git aint set <id> --add-dep <other-id>     # add dependency (with cycle detection)
git aint set <id> --slug new-name          # rename file/directory
git aint set <id> --in <parent-id>         # move to different parent (file-form only)
git aint set <id> --editor                 # open in editor
git aint rm <id>                           # remove aint (dir-form: removes recursively)
git aint rm <id> --file rfc.md             # remove one file from aint directory
git aint sync                              # pull/commit/push + regenerate auto_state.md
git aint sync --dry-run                    # show what would be committed
git aint doctor                            # validate all aints
git aint doctor --fix                      # auto-fix safe issues
git aint exec <id> -- <cmd>                # run command in aint worktree
```

## Compound Operations (shell script aliases)

```bash
git aint pickup <id>              # create worktree + branch + set working
git aint reject <id>              # set rejected + optional reason
git aint cleanup                  # remove stale worktrees/branches/tmux
git aint whats-next               # show unblocked open aints
git aint worktree list            # show all managed worktrees
git aint worktree status          # git status in each worktree
git aint worktree remove <id>     # remove worktree + clean tags
git aint tmux attach <id>         # attach/create tmux session
git aint tmux list                # show all tmux sessions
git aint tmux kill <id>           # kill tmux session
git aint aliases                  # list all aliases with descriptions
```

## File Structure

```
.aint/
  active/                           # open/working/pushed aints
    aint.fix-auth.ab12c.md          # file-form aint
    aint.gateway-rearch.ef56g/      # directory-form aint
      aint.md                       # aint metadata (ID from directory name)
      rfc.md                        # supporting doc (free-format)
      aint.strip-pg.cd34h.md        # child aint
  archive/                          # merged/rejected aints (same structure)
  scripts/                          # shell scripts for aliases
  docs/                             # static reference docs
  trash/                            # ephemeral scratch (plans)
  auto_state.md                     # auto-generated project state
  AGENTS.md                         # this file
```

## Frontmatter

```yaml
---
title: "Fix auth redirect"
status: open
priority: 2
assignee: alice
dependencies: [zz99q]
tags:
  - pr:401
  - worktree:.worktrees/ab12c.fix-auth
  - branch:ab12c.fix-auth
reason: optional status-change reason
---

Markdown body (free-form).
```

Required: `title`. Defaults: `status: open`, `priority: 2`. Everything else optional.

## Output Formats (-o flag)

`table` (default) | `tree` | `detail` | `files` | `wide` | `json` | `yaml`

Custom: `--format "{id} {title} {status} {tag:worktree} {config:KEY}"`

## Composition & Dependencies

- **Composition** (parent/child): expressed by filesystem nesting — child aints live inside parent directory
- **Dependencies** (ordering): expressed in frontmatter `dependencies: [id1, id2]` — cross-directory, cycle-checked

## References

- Bare 5-char ID: `ab12c`
- All commands accept bare IDs

## Hackability

The data model is plain files and YAML. You can edit files directly with any
tool and run `git aint sync` to commit (or commit manually in `.aint/` dir). The
only hard rules: filenames must match `aint.{slug}.{id}.md`, and frontmatter must have `title:`.

## When Something Goes Wrong

1. Run `git aint <command> --help` — the CLI's own help is always up-to-date
2. Run `git aint doctor --fix` — auto-fixes common structural issues
3. Read deeper guides in `.aint/docs/git-aint/` (created by `git aint init`):
   - `cli/` — per-command reference (get, set, new, rm, sync, doctor, exec, init)
   - `workflows.md` — step-by-step multi-aint feature workflows
   - `worktrees.md` — worktree lifecycle and development patterns
   - `troubleshooting.md` — common problems and fixes
4. Edit files directly in `.aint/` and run `git aint sync` — it's just markdown and YAML

## Current Project State

@auto_state.md
