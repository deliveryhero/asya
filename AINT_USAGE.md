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
git aint list -s "query" -o tree       # search + tree view

# Read
git aint get <ref>                     # details (-o json for structured)

# Create
git aint create -t "Title" -p 2                  # task (P2 = medium)
git aint create -t "Title" --epic init --dep init/1bm2  # with epic + dep

# Update
git aint update <ref> --status active             # pick up
git aint update <ref> --status vibed             # close
git aint update <ref> --add-tag "pr:123"         # tag a PR
```

All commands support `-o json`. Run `git aint <cmd> --help` for full options.

## Aint References

- Epic: `init` — base-36 generated ID (default 6 chars, configurable via `git config aint.id-length`)
- Task: `init/1bm2cd` — epic/task, IDs are base-36
- Status: `active` | `ideated` | `ready` | `vibed` | `yeeted`
- Priority: `0` critical, `1` high, `2` medium, `3` low, `4` backlog

## Workflow

1. `git aint list` — see open aints
2. `git aint pickup <ref>` — (git alias) creates worktree + branch, sets status to active
3. Work in the worktree at `.worktrees/<epic>/<task>.<slug>`
4. `git aint update <ref> --status vibed` — close when finished

### Worktrees

All work should be done in a git worktree. `git aint pickup <ref>` automates this:
- Creates branch `<epic>/<task>.<slug>` (e.g. `init/1bm2.implmnt-auth`)
- Creates worktree in `.worktrees/` (configurable via `git config aint.worktree-dir`)
- Tags the aint with `worktree:<branch>`
- Sets status to `active`

## File Structure

```
.aint/epics/
├── 1b0.init/                    # epic directory (<id>.<slug>)
│   ├── epic.md                  # epic metadata (YAML frontmatter)
│   ├── rfc.md                   # optional RFC/design doc
│   ├── adr.chose-yaml.md        # optional ADR
│   ├── task.1bm2.implmnt-auth.md  # task file (task.<id>.<slug>.md)
│   └── task.1bt9.fix-store.md   # each task ≈ 1 PR, ~2 min AI task
├── 1bp.publish/
│   └── ...
└── misc/                        # default epic for uncategorized tasks
```

- **epic.md**: epic metadata (YAML frontmatter + brief description)
- **rfc.md**: optional RFC/design doc, typically created collaboratively
  by brainstorming with the user
- **adr.*.md**: optional architecture decision records
- **Task files**: YAML frontmatter (status, priority, deps, tags) + markdown
  body. File naming (`task.<id>.<slug>.md`) is parsed by git-aint — don't rename
- **Conflicts**: since `.aint/` is a git worktree, resolve conflicts with
  `git -C .aint/ ...` (e.g. `git -C .aint/ merge --abort`)

## Conventions

- **Branches**: `<epic>/<task>.<slug>` (e.g. `1bd2/1bm2.implmnt-auth`)
- **Tags**: `worktree:<branch>`, `pr:<number>`
- **Dependencies**: aint refs in frontmatter (e.g. `dependencies: [init/1bm2]`)
