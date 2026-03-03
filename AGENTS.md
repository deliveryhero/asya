# git-aint: Agent Instructions

This project uses **git-aint** for issue tracking.

## How It Works

Aints (issues) are markdown files with YAML frontmatter stored in `.aint/epics/`.
The `.aint/` directory is a **git worktree** on the `aint-sync` branch — it's
gitignored from the main branch. Don't `git add` it from main.

Sync happens automatically: every `git aint create` / `update` auto-commits and
pushes to `aint-sync`. For manual sync: `git aint sync` (runs pull/commit/push
inside `.aint/`).

Most commands are **git aliases** seeded by `git aint init`. If something breaks,
check `git config --get-regexp aint.alias` to debug.

## Commands

```bash
# List & filter
git aint list                          # open aints
git aint list --search "query" --output tree  # search + tree view

# Read
git aint get <ref>                     # details (--output json for structured)

# Create
git aint create --title "Title" --priority 2            # task (P2 = medium)
git aint create --title "Title" --epic init --dep init/1bm2  # with epic + dep

# Update
git aint update <ref> --status afoot             # pick up
git aint update <ref> --status vibed             # close
git aint update <ref> --add-tag "pr:123"         # tag a PR

# Review & deprioritize
git aint peep <ref>                              # approve (sets status to peeped)
git aint snooze <ref>                            # deprioritize (sets status to snoozed)
```

All commands support `--output json`. Run `git aint <cmd> --help` for full options.

## Aint References

- Epic: `init` — base-36 generated ID (default 6 chars, configurable via `git config aint.id-length`)
- Task: `init/1bm2cd` — epic/task, IDs are base-36
- Task status: `slopped` | `peeped` | `afoot` | `snoozed` | `vibed` | `yeeted`
- Epic state: open (in `epics/`) or closed (in `epics/.closed/`) — no status field
- Priority: `0` critical, `1` high, `2` medium, `3` low, `4` backlog

## Workflow

1. `git aint list` — see open aints
2. `git aint pickup <ref>` — (git alias) creates worktree + branch, sets status to afoot
3. Work in the worktree at `.worktrees/<epic>/<task>.<slug>`
4. `git aint update <ref> --status vibed` — close when finished

### Worktrees

All work should be done in a git worktree. `git aint pickup <ref>` automates this:
- Creates branch `<epic>/<task>.<slug>` (e.g. `init/1bm2.implmnt-auth`)
- Creates worktree in `.worktrees/` (configurable via `git config aint.worktree-dir`)
- Tags the aint with `worktree:<worktree-path>` and `branch:<branch>`
- Sets status to `afoot`

## File Structure

```
.aint/epics/
├── .closed/                     # closed epics (moved here when done)
│   └── 1iv.rework-status/
│       └── epic.md
├── 1b0.init/                    # open epic directory (<id>.<slug>)
│   ├── epic.md                  # epic metadata (YAML frontmatter, no status)
│   ├── rfc.md                   # optional RFC/design doc
│   ├── adr.chose-yaml.md        # optional ADR
│   ├── .closed/                 # closed tasks within the epic
│   │   └── task.vibed.1bt9.fix-store.md
│   └── task.slopped.1bm2.implmnt-auth.md  # task.<status>.<id>.<slug>.md
├── 1bp.publish/
│   └── ...
└── misc/                        # default epic for uncategorized tasks
```

- **epic.md**: epic metadata (YAML frontmatter + brief description). No status
  field — epics are open (in `epics/`) or closed (moved to `epics/.closed/`)
- **rfc.md**: optional RFC/design doc, typically created collaboratively
  by brainstorming with the user
- **adr.*.md**: optional architecture decision records
- **Task files**: YAML frontmatter (priority, deps, tags) + markdown body.
  Status is encoded in the filename (`task.<status>.<id>.<slug>.md`). Closed
  tasks are moved to `.closed/` within the epic directory
- **Conflicts**: since `.aint/` is a git worktree, resolve conflicts with
  `git -C .aint/ ...` (e.g. `git -C .aint/ merge --abort`)

## Conventions

- **Branches**: `<epic>/<task>.<slug>` (e.g. `1bd2/1bm2.implmnt-auth`)
- **Tags**: `worktree:<worktree-path>`, `branch:<branch>`, `pr:<number>`
- **Dependencies**: aint refs in frontmatter (e.g. `dependencies: [init/1bm2]`)
