# `git aint sync`

Sync manual changes in the `.aint/` worktree — pull, commit, push.

Use this when you've edited aint files by hand (outside of `git aint` commands)
and need to commit and push those changes. All `git aint` write commands (new, set, rm)
auto-sync by default, so manual syncing is mainly for hand-edited files.

## Usage

```
git aint sync [options]
```

## What it does

### 1. Branch validation

Checks that `.aint/` is on the `aint-sync` branch. If it's on a leftover conflict
branch (from a failed rebase), prints resolution instructions.

### 2. Pull (if auto-pull enabled)

- Resets `auto_state.md` to HEAD before pulling — this discards the local copy
  since it will be regenerated after pull anyway, preventing merge conflicts.
  (A `.gitattributes` merge driver set up by [`init`](init.md) provides a
  secondary safety net.)
- Runs `git pull --rebase`.
- Falls back to explicit `git pull --rebase origin aint-sync` if needed.

### 3. Change detection

Parses `git status --porcelain` to find modified/added/deleted files.
If nothing changed and `--summarize` wasn't given, exits with "Nothing to sync."

### 4. `auto_state.md` regeneration

When changes are detected (or `--summarize` is passed), regenerates `auto_state.md`
before committing so it's included in the same commit. This file is a concise,
AI-readable summary of project state (see [auto_state.md](#auto_statemd) below).

### 5. Commit (if auto-commit enabled)

- Stages all changes with `git add -A`.
- Generates a semantic commit message from the changes (e.g., `aint: updated [ab12c]`),
  or uses `--message` if provided.
- Uses `--no-verify` to skip pre-commit hooks on the aint-sync branch.

### 6. Push (if auto-push enabled)

- Pushes with retry (up to 3 attempts).
- On push failure, tries `pull --rebase` and retries.

## Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Show what would be committed, don't do it |
| `--message <TEXT>` | Override auto-generated commit message |
| `--summarize` | Force `auto_state.md` regeneration even without changes |
| `--no-commit` | Skip commit and push |
| `--no-push` | Skip push only |
| `--no-pull` | Skip pull |
| `--output json\|yaml\|table` | Output format |

## Configuration

Sync phases can be toggled via git config:

```
git config aint.auto-pull true    # default: true
git config aint.auto-commit true  # default: true
git config aint.auto-push true    # default: true
```

These apply to all write commands (new, set, rm) as well as sync.

## `auto_state.md`

The auto-generated state file provides a prioritized summary for AI agents:

- **Scoring:** Each aint is scored by status weight (working=100, pushed=80, open=10),
  recency (exponential decay over last N commits/days), dependency proximity (blocks/blocked-by
  working aints), composition proximity (parent/child of working aints), and priority bonus.
- **Tiers:** Working aints get full detail (path, docs, children). Recently modified aints
  get path. Others get one-line summaries. Capped at `max-aints`.
- **Closed:** Shows the N most recently closed aints at the end.

Configuration:

| Config key | Default | Effect |
|-----------|---------|--------|
| `aint.state.max-commits` | 50 | Git log depth for recency |
| `aint.state.max-days` | 14 | Time window for recency |
| `aint.state.dep-depth` | 2 | Dependency traversal depth |
| `aint.state.max-aints` | 20 | Max aints shown |
| `aint.state.show-closed` | 5 | Number of closed aints to show |

## Examples

```
$ git aint sync --dry-run
Changes to sync:
  modified: [ab12c] (active/aint.fix-auth.ab12c.md)
  new: [ef56g] (active/aint.add-api.ef56g.md)

Use `git aint sync` (without --dry-run) to commit and push.

$ git aint sync
Synced 2 changes
  [ab12c] modified
  [ef56g] created
```
