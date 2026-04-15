# Aliases (compound operations)

Aliases use git's built-in alias mechanism. `git aint init` writes entries like
`aint.alias.pickup = !bash .aint/scripts/pickup.sh "$@"` into `.git/config`.
Git resolves `git aint pickup` → `git-aint pickup` → the alias, which shells
out to the script in `.aint/scripts/`.

This means aliases work exactly like any other git alias — they show up in
`git config --list`, can be overridden per-repo, and are resolved by git itself.
Descriptions are stored alongside in `aint.alias-desc.*` keys.

Three aliases (`aliases`, `cleanup`, `whats-next`) are pure git-aint invocations
rather than shell scripts. The rest dispatch to `.sh` files.

`git aint init` only adds missing aliases — it never overwrites user customizations
unless you pass `--overwrite-aliases`.

Run `git aint aliases` to list all available aliases with descriptions.

---

## `pickup`

Create a worktree and start working on an aint.

```
git aint pickup <ref>
```

**What it does:**

1. Rejects closed aints (merged/rejected).
2. Resolves branch name and worktree path from config patterns
   (`aint.branch-pattern`, `aint.worktree-pattern`, `aint.worktree-dir`).
3. Creates a git worktree idempotently — reuses if it already exists.
4. Sets status to `working` and adds `worktree:` and `branch:` tags.
5. Prints a summary with next-step commands.

**Output:**

```
Picked up [ab12c] in /repo/.worktrees/ab12c.fix-auth
  tmux:    $ git aint tmux attach ab12c
  exec:    $ git aint exec ab12c -- git status
  finish:  $ git aint set ab12c --status merged
```

---

## `cleanup`

Remove stale worktrees, branches, tmux sessions, and archive closed aints.

```
git aint cleanup
```

Shorthand for: `git aint doctor --fix --only clean-worktrees,clean-branches,clean-tmux,clean-aints`

---

## `whats-next`

Show unblocked aints ready to work on.

```
git aint whats-next
```

Shorthand for: `git aint get --status open --deps clear`

---

## `reject`

Reject an aint with an optional reason.

```
git aint reject <ref> [--reason "superseded by XYZ"]
```

Sets status to `rejected` and optionally sets the reason field.

---

## `worktree` (git worktree management)

```
git aint worktree list              # show all managed worktrees with status
git aint worktree status            # show git status in each worktree
git aint worktree remove <ref>      # remove worktree and clean up tags
```

### `worktree list`

Queries live git worktrees (filtered to the managed worktree directory) and
cross-references each with its aint to show status and title.

### `worktree status`

Shows uncommitted changes in each worktree by running `git status --short`
via `git aint exec` for every aint with a `worktree` tag.

### `worktree remove`

Removes the worktree directory (`git worktree remove`) and cleans up
the `worktree:` and `branch:` tags on the aint.

---

## `tmux` (terminal session management)

```
git aint tmux attach <ref>    # attach to or create a tmux session
git aint tmux list            # show all tmux sessions with aint info
git aint tmux kill <ref>      # kill a session
git aint tmux cleanup [--fix] # find and optionally kill orphaned sessions
```

### `tmux attach`

Creates a tmux session named after the aint (using `aint.tmux-session-pattern`)
if it doesn't exist. The session's working directory is the aint's worktree
(if it exists) or the repo root. Attaches or switches to the session.

### `tmux list`

Lists all tmux sessions and cross-references each with its aint (by extracting
the aint ID from the session name).

### `tmux cleanup`

Finds sessions whose aint is closed (merged/rejected) or doesn't exist.
With `--fix`, kills those sessions.

---

## `really` (themed health checks)

```
git aint really elegant       # show philosophy docs
git aint really tracking      # run sync validation
git aint really hygienic      # clean worktrees, branches, tmux, aints
git aint really configured    # run init (ensure all configs set)
git aint really helping       # show stats summary
git aint really working       # run full doctor checks
```

---

## `just` (philosophy docs)

```
git aint just                 # list available topics
git aint just a tool          # show "just-a-tool.md"
git aint just beads           # show "just-beads.md"
```

Topics are markdown files in `.aint/scripts/md/just-*.md`. You can add your
own by creating files in that directory.
