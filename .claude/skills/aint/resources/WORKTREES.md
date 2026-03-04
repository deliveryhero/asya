# Worktrees

Worktree-based development patterns with git-aint.

## Overview

git-aint uses git worktrees to provide isolated workspaces per aint. Each aint
gets its own branch and directory, keeping work separated and making context
switches clean.

There are two distinct worktrees in play:
1. **`.aint/` worktree** -- holds issue data on the `aint-sync` branch (managed by git-aint)
2. **Task worktrees** -- created by `pickup` in `.worktrees/` for doing actual code work

This document covers task worktrees (#2).

---

## How `git aint pickup` Works

```bash
git aint pickup <ref>
```

### What it does

1. **Creates a branch** named `<dir>/<id>.<slug>` (e.g. `ci-setup/c9x8.fix-auth`)
2. **Creates a worktree** in `.worktrees/ci-setup/c9x8.fix-auth`
3. **Tags the aint** with `worktree:<worktree-path>` and `branch:<branch>`
4. **Sets status** to `active`

### Example

```bash
$ git aint pickup c9x8

# Result:
# Branch:   ci-setup/c9x8.fix-auth
# Worktree: .worktrees/ci-setup/c9x8.fix-auth/
# Status:   active
# Tags:     worktree:.worktrees/ci-setup/c9x8.fix-auth
#           branch:ci-setup/c9x8.fix-auth
```

---

## Directory Structure

```
project-root/
├── .aint/                                 # issue data worktree (aint-sync branch)
│   └── aints/
│       └── ...
├── .worktrees/                            # task worktrees (configurable)
│   ├── ci-setup/
│   │   └── c9x8.fix-auth/                # worktree for aint c9x8
│   │       ├── src/
│   │       └── ...                        # full repo checkout on aint branch
│   └── misc/
│       └── d4m1.fix-bug/                  # worktree for aint d4m1
├── src/                                   # main branch working directory
└── ...
```

### Configuring the worktree directory

```bash
git config aint.worktree-dir /path/to/worktrees
```

---

## Lifecycle

| Phase | Aint Status | Worktree State |
|-------|-------------|----------------|
| Created | `open` | No worktree |
| Pickup | `active` | Worktree created, branch checked out |
| Working | `active` | Commits on aint branch |
| PR created | `pushed` | Push branch, tag with `pr:NUMBER` |
| Merged | `merged` | Worktree can be cleaned up |

### Typical flow

```bash
# 1. Pick up (creates worktree)
git aint pickup c9x8

# 2. Work in the worktree
cd .worktrees/ci-setup/c9x8.fix-auth/
# ... make changes, commit ...

# 3. Push and create PR
git aint push c9x8

# 4. After merge, mark complete
git aint update c9x8 --status merged

# 5. Cleanup (doctor handles this)
git aint doctor --only clean-worktrees --fix
```

---

## Finding Worktree/Aint Mapping

```bash
# Get worktree path from aint
git aint get c9x8 --format "{tag:worktree}"

# Get branch name from aint
git aint get c9x8 --format "{tag:branch}"

# Find aint for a branch
git aint list --tag "branch:ci-setup/c9x8.fix-auth"
```

---

## Troubleshooting

### Worktree already exists

```bash
git worktree list                         # see all worktrees
ls .worktrees/                            # check directory
```

### Branch already exists

```bash
git branch -D ci-setup/c9x8.fix-auth     # delete old branch
git aint pickup c9x8                      # try again
```

### Conflicts with .aint/ worktree

```bash
git -C .aint/ status                      # check status
git -C .aint/ merge --abort               # abort if needed
git aint sync                             # re-sync
```
