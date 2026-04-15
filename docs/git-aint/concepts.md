# Concepts

Core concepts behind git-aint's data model and operations.

## Aint storage

All aints live in the `.aint/` directory, which is a git worktree on the orphan
`aint-sync` branch. This separates issue tracking data from your main code branch.

```
.aint/
  active/       # aints being worked on (open, working, pushed)
  archive/      # completed aints (merged, rejected)
  scripts/      # compound operation shell scripts
  docs/         # static reference docs
  trash/        # ephemeral scratch
  auto_state.md # auto-generated projec .t state for AI agents
  AGENTS.md     # agent instructions
```

## Two forms of aints

### File-form

A single markdown file. Used for standalone aints.

```
.aint/active/aint.fix-auth.ab12c.md
```

### Directory-form

A directory containing `aint.md` plus supporting files and child aints.
Used for epics or aints that need RFCs, ADRs, or other documents.

```
.aint/active/aint.gateway-rearch.ef56g/
  aint.md                       # the aint itself
  rfc.md                        # supporting document
  aint.strip-pg.cd34h.md        # child aint (file-form)
  aint.add-cache.gh78i/         # child aint (dir-form)
    aint.md
```

## Naming convention

- **File:** `aint.{slug}.{id}.md`
- **Directory:** `aint.{slug}.{id}/` with `aint.md` inside
- **IDs:** Random base-36, 3-8 chars (default 5)
- **Slugs:** Auto-generated from title, human-readable

## Statuses and file location

| Status | Location | Meaning |
|--------|----------|---------|
| `open` | `active/` | Ready to work on |
| `working` | `active/` | Being worked on |
| `pushed` | `active/` | Branch pushed / PR open |
| `merged` | `archive/` | Completed |
| `rejected` | `archive/` | Closed without completing |

When status changes between active and closed, the file (or directory) is
physically moved between `active/` and `archive/`.

## Composition (parent/child)

Expressed by **filesystem nesting**. Child aints live inside a parent's directory:

```
active/aint.parent.ab12c/      # parent (dir-form)
  aint.md                       # parent metadata
  aint.child.ef56g.md           # child (file-form)
```

Children can be file-form or directory-form. When a parent is closed, any
remaining open children block the operation (unless `--force` is used).

## Dependencies (ordering)

Expressed in **frontmatter** via `dependencies: [id1, id2]`. Dependencies are
cross-directory — any aint can depend on any other aint by bare ID.

```yaml
---
title: "Deploy to production"
dependencies: [ab12c, ef56g]
---
```

Cycle detection runs on every `--add-dep` to prevent circular dependencies.

Use `git aint get --deps clear` to find unblocked aints (all dependencies closed).

## Tags

Key-value pairs stored in frontmatter. Some tags have special meaning:

| Tag | Set by | Purpose |
|-----|--------|---------|
| `worktree:<path>` | `pickup` | Path to git worktree |
| `branch:<name>` | `pickup` | Branch name |
| `pr:<number>` | User/CI | GitHub PR number |

## Auto-sync

All write commands (`new`, `set`, `rm`) auto-sync by default:

1. **Pull** — rebase from remote before writing
2. **Write** — apply changes to disk
3. **Commit** — stage and commit with semantic message
4. **Push** — push to remote with retry

Each phase is toggleable via `--no-pull`, `--no-commit`, `--no-push`, or
git config (`aint.auto-pull`, `aint.auto-commit`, `aint.auto-push`).

## Git config

All configuration lives in git config under the `aint.*` namespace.
Defaults are seeded by `git aint init` and can be overridden:

```
git config aint.id-length 5
git config aint.slug-token-len 8
git config aint.slug-max-tokens 3
git config aint.auto-pull true
git config aint.auto-commit true
git config aint.auto-push true
git config aint.worktree-dir .worktrees
git config aint.editor vscode
```
