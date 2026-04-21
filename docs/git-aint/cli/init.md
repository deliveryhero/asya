# `git aint init`

Set up the `.aint/` worktree and seed default configuration.
Safe to run multiple times — every step is idempotent.

## Usage

```
git aint init [--overwrite-aliases]
```

## What it does

1. **Creates the `aint-sync` orphan branch** (or finds an existing one locally/remotely).
2. **Adds `.aint/` as a git worktree** pointing at that branch.
3. **Writes managed files** that are refreshed on every run:
   - `.aint/.gitignore` — tracks `active/`, `archive/`, `scripts/`, `docs/`, `trash/`, `auto_state.md`, `AGENTS.md`
   - `.aint/.gitattributes` — assigns the `regenerate` merge driver to auto-generated files (see below)
   - `.aint/scripts/*.sh` — shell scripts for compound aliases (always overwritten)
   - `.aint/scripts/md/` — static markdown files
4. **Seeds git config defaults** (only if not already set):
   - Aliases: `aliases`, `cleanup`, `whats-next`, plus all script-based aliases
   - Config values under `aint.*`
   - Merge driver `regenerate` for auto-generated files (see below)
5. **Pushes to remote** on first init; pulls from remote on subsequent inits.
6. **Configures agent integrations** — auto-detects Claude, GitHub, etc. and patches agent instruction files.
7. **Writes `.ignore`** — marks `.aint/` for IDE file indexing.

## Idempotency

| Step | First run | Subsequent runs |
|------|-----------|-----------------|
| Branch | Creates orphan `aint-sync` | Reuses existing |
| Worktree | `git worktree add .aint/` | Prunes stale, reuses existing |
| Scripts | Written fresh | Overwritten (always current) |
| Aliases | Added | Skipped if already set |
| Config | Seeded | Skipped if already set |
| Remote push | Pushes | Pulls instead |

Running `init` after a `git clone` fetches the remote `aint-sync` branch and sets up
the worktree from it — existing aints are preserved.

## Flags

| Flag | Effect |
|------|--------|
| `--overwrite-aliases` | Overwrite aliases that differ from defaults (normally user customizations are preserved) |

## Init results

The output header tells you what happened:

- **initialized aint tracking:** — fresh setup, new branch created
- **initialized aint tracking (from remote):** — fetched existing `aint-sync` from origin
- **initialized aint tracking (existing branch):** — local `aint-sync` already existed
- **reinitialized aint tracking:** — repaired a stale or broken worktree

## Merge driver for auto-generated files

`init` sets up a custom git merge driver called `regenerate` that prevents
merge conflicts on files that are regenerated on every sync. Two things are
configured:

1. **`.git/config`** (main repo config):
   ```
   [merge "regenerate"]
       name = Auto-accept local for regenerated files
       driver = true
   ```
   `driver = true` tells git to always keep the local version on conflict.

2. **`.aint/.gitattributes`** (on the `aint-sync` branch):
   ```
   **/auto-generated.md merge=regenerate
   ```
   Assigns the driver to matching files.

This is a safety net. The primary conflict prevention is in `sync`, which
resets `auto_state.md` to HEAD before every pull (discarding the local copy
that's about to be regenerated anyway). See [`sync`](sync.md) for details.

## Example output

```
initialized aint tracking:
  branch:    aint-sync
  worktree:  .aint/
  scripts:   .aint/scripts/ (18 files)
  aliases:   3 added (cleanup, whats-next, pickup)
  remote:    pushed to origin/aint-sync
```
