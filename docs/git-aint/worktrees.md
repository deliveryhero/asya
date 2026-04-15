# Worktrees

git-aint uses git worktrees in two distinct ways: one for storing aint data, and
another for isolating code work on individual aints.

## Two worktrees

### The data worktree (`.aint/`)

The `.aint/` directory is a git worktree on the orphan `aint-sync` branch. It
holds all aint files, scripts, and auto-generated state. This branch has no
connection to your main code branch -- it is a separate history tracking only
issue data.

`git aint init` creates this worktree. Every write command (`new`, `set`, `rm`)
auto-commits and pushes to `aint-sync`. The `.aint/` directory is gitignored on
your main branch.

### Task worktrees (`.worktrees/`)

When you pick up an aint with `git aint pickup`, a new git worktree is created
under `.worktrees/` (configurable via `aint.worktree-dir`). Each worktree gets
its own branch, so you can work on multiple aints simultaneously without
switching branches in your main checkout.

## Directory structure

A typical repo with active worktrees looks like this:

```
my-project/
  .aint/                                    # data worktree (aint-sync branch)
    active/
      aint.fix-auth.ab12c.md
      aint.api-rate-limiting.k8m2p/
        aint.md
        rfc.md
    archive/
    scripts/
    auto_state.md
  .worktrees/                               # task worktrees (one per aint)
    ab12c.fix-auth/                         # full repo checkout on its own branch
    r3x9w.design-token-bucket/
  src/                                      # main checkout
  ...
```

The `.worktrees/` directory is also gitignored. Each subdirectory is a full git
working tree with its own branch checked out.

## How pickup works

`git aint pickup <ref>` is a compound operation that:

1. **Validates** that the aint is not already closed (merged/rejected).
2. **Resolves** the branch name and worktree path from config patterns:
   - Branch: `aint.branch-pattern` (default: `{id}.{slug}`)
   - Worktree path: `aint.worktree-dir` + `aint.worktree-pattern`
3. **Creates** a git worktree with `git worktree add`, using the resolved branch
   name. If the worktree already exists, it is reused (idempotent).
4. **Updates** the aint: sets status to `working`, adds `worktree:` and `branch:`
   tags to the frontmatter.
5. **Prints** next-step commands.

Example:

```bash
git aint pickup ab12c
# Picked up [ab12c] in /repo/.worktrees/ab12c.fix-auth
#   tmux:    $ git aint tmux attach ab12c
#   exec:    $ git aint exec ab12c -- git status
#   finish:  $ git aint set ab12c --status merged
```

After pickup, the aint's frontmatter looks like:

```yaml
---
title: "Fix auth redirect"
status: working
priority: 1
tags:
  - worktree:.worktrees/ab12c.fix-auth
  - branch:ab12c.fix-auth
---
```

## Lifecycle

The table below shows the relationship between aint status and worktree state:

| Status | Worktree | Branch | What happens |
|--------|----------|--------|-------------|
| `open` | Does not exist | Does not exist | Aint is ready to be picked up |
| `working` | Exists in `.worktrees/` | Exists, checked out in worktree | Active development |
| `pushed` | Exists in `.worktrees/` | Pushed to remote, PR may be open | Waiting for review/merge |
| `merged` | Stale (candidate for cleanup) | Merged into main | `cleanup` removes worktree and branch |
| `rejected` | Stale (candidate for cleanup) | May or may not be merged | `cleanup` removes worktree and branch |

## Running commands in worktrees

`git aint exec` runs a command inside an aint's worktree directory. It resolves
the worktree path from the aint's `worktree` tag.

```bash
# Run git status in the aint's worktree
git aint exec ab12c -- git status

# Run tests
git aint exec ab12c -- cargo test

# Run any command
git aint exec ab12c -- ls -la
```

Template placeholders are expanded in command arguments:

```bash
# Push the aint's branch
git aint exec ab12c -- git push -u origin {tag:branch}

# Print the aint's title
git aint exec ab12c -- echo {title}
```

Available placeholders: `{id}`, `{slug}`, `{title}`, `{status}`, `{priority}`,
`{assignee}`, `{ref}`, `{path}`, `{dir}`, `{dir_slug}`, `{tag:KEY}`,
`{config:KEY}`.

If the aint does not have a `worktree` tag, `exec` fails with a hint to run
`git aint pickup` first.

## Finding mappings

Use `--format` to extract tag values and find relationships between aints,
worktrees, and branches.

**Find the worktree for an aint:**

```bash
git aint get ab12c --format "{tag:worktree}"
# .worktrees/ab12c.fix-auth
```

**Find the branch for an aint:**

```bash
git aint get ab12c --format "{tag:branch}"
# ab12c.fix-auth
```

**Find an aint by its branch:**

```bash
git aint get --tag "branch:ab12c.fix-auth"
```

**Find an aint by its worktree:**

```bash
git aint get --tag "worktree:.worktrees/ab12c.fix-auth"
```

## Worktree management

The `worktree` alias provides subcommands for managing task worktrees.

### `worktree list`

```bash
git aint worktree list
```

Shows all managed worktrees (those under the configured `aint.worktree-dir`)
with their branch, aint status, and title.

```
BRANCH                                    STATUS      TITLE
ab12c.fix-auth                            working     Fix auth redirect
r3x9w.design-token-bucket                 pushed      Design token bucket algorithm
```

### `worktree status`

```bash
git aint worktree status
```

Shows uncommitted changes in each worktree by running `git status --short` via
`git aint exec` for every aint with a `worktree` tag.

```
[ab12c]:
  M src/auth.rs
   M tests/auth_test.rs

[r3x9w]:
  (clean)
```

### `worktree remove`

```bash
git aint worktree remove ab12c
```

Removes the worktree directory (`git worktree remove`) and cleans up the
`worktree:` and `branch:` tags on the aint. Use this when you want to remove
a worktree without changing the aint's status.

## Tmux integration

The `tmux` alias manages tmux sessions tied to aints. Sessions are named using
`aint.tmux-session-pattern` (default: `{id}`).

### `tmux attach`

```bash
git aint tmux attach ab12c
```

Creates a tmux session named after the aint if it does not already exist. The
session's working directory is set to the aint's worktree (if it exists) or the
repo root. If you are already inside tmux, it switches to the session; otherwise
it attaches.

### `tmux list`

```bash
git aint tmux list
```

Lists all tmux sessions and cross-references each with its aint (by extracting
the aint ID from the session name).

```
SESSION                         STATUS      TITLE
ab12c                           working     Fix auth redirect
r3x9w                           pushed      Design token bucket algorithm
```

### `tmux kill`

```bash
git aint tmux kill ab12c
```

Kills the tmux session for the given aint.

### `tmux cleanup`

```bash
git aint tmux cleanup
git aint tmux cleanup --fix
```

Finds sessions whose aint is closed (merged/rejected) or does not exist.
Without `--fix`, lists orphaned sessions. With `--fix`, kills them.

## Cleanup

Two cleanup mechanisms remove stale worktrees, branches, and tmux sessions:

### `git aint cleanup`

The all-in-one alias. It is shorthand for:

```bash
git aint doctor --fix --only clean-worktrees,clean-branches,clean-tmux,clean-aints
```

This:

- Removes worktrees whose branch is merged into main, or whose aint is closed.
- Deletes local branches whose remote tracking branch is gone (`[gone]`).
- Kills orphaned tmux sessions.
- Moves any stale aints from `active/` to `archive/` if their status is closed.

Worktrees with uncommitted changes are skipped and flagged as blocked.

### `git aint doctor --fix`

The full health check with optional auto-repair. The cleanup-related checks are:

| Check | What it does |
|-------|-------------|
| `clean-worktrees` | Removes worktrees for merged branches or closed aints |
| `clean-branches` | Deletes local branches whose remote tracking branch is gone |
| `clean-tmux` | Kills tmux sessions for closed or missing aints |
| `clean-aints` | Moves closed aints from `active/` to `archive/` |

These checks only run when explicitly selected via `--only`. Without `--only`,
`doctor` runs validation checks only (frontmatter, references, sync status).

Run targeted cleanup:

```bash
# Just clean up worktrees
git aint doctor --fix --only clean-worktrees

# Preview what would be cleaned (without --fix)
git aint doctor --only clean-worktrees
```

## Configuration

All worktree and branch patterns are configurable via git config:

| Config key | Default | Description |
|-----------|---------|-------------|
| `aint.worktree-dir` | `.worktrees` | Directory for task worktrees (relative to repo root) |
| `aint.branch-pattern` | `{id}.{slug}` | Branch naming pattern |
| `aint.worktree-pattern` | (matches branch pattern if set) | Subdirectory name under worktree-dir |
| `aint.tmux-session-pattern` | `{id}` | Tmux session naming pattern |

Patterns support the same placeholders as `--format`: `{id}`, `{slug}`,
`{title}`, `{tag:KEY}`, `{config:KEY}`, etc.

**Change the worktree directory:**

```bash
git config aint.worktree-dir .wt
```

**Use a different branch naming convention:**

```bash
# Include slug only
git config aint.branch-pattern "{slug}"

# Include a prefix
git config aint.branch-pattern "feature/{id}.{slug}"
```

**Customize tmux session names:**

```bash
git config aint.tmux-session-pattern "{id}.{slug}"
```

These values are seeded by `git aint init` and can be overridden at any time.

## Troubleshooting

### Worktree already exists

If `git aint pickup` says the worktree already exists, it reuses it. This is
by design -- pickup is idempotent. If you need to recreate it from scratch:

```bash
git aint worktree remove ab12c
git aint pickup ab12c
```

### Branch already exists

If the branch already exists (from a previous pickup or manual creation),
`git worktree add` falls back to checking out the existing branch instead
of creating a new one. If the branch points to an unexpected commit:

```bash
git aint worktree remove ab12c
git branch -D ab12c.fix-auth
git aint pickup ab12c
```

### Stale worktrees

If a worktree directory was manually deleted (e.g., `rm -rf .worktrees/ab12c.fix-auth`),
git still tracks a stale reference. Fix it with:

```bash
git worktree prune
```

Then clean up the aint's tags:

```bash
git aint set ab12c --rm-tag "worktree:.worktrees/ab12c.fix-auth" --rm-tag "branch:ab12c.fix-auth"
```

Or let doctor handle it:

```bash
git aint doctor --fix --only clean-worktrees
```

### Worktree has uncommitted changes

`git aint cleanup` will not remove a worktree that has uncommitted changes. It
reports these as "blocked" candidates. Either commit or stash your changes first,
or use `git worktree remove --force` manually.

### The .aint/ worktree is on the wrong branch

If `git aint sync` reports that `.aint/` is on the wrong branch (not `aint-sync`),
this usually means a previous sync had a rebase conflict. Follow the hint in the
error message:

```bash
cd .aint
git checkout aint-sync
git merge <conflict-branch>
git branch -d <conflict-branch>
git push
```
