# git-aim: Agent Instructions

This project uses **git-aim** for issue tracking.

## How It Works

Aims (issues) are markdown files with YAML frontmatter stored in `.aim/aims/`.
The `.aim/` directory is a **git worktree** on the `aim-sync` branch — it's
gitignored from the main branch. Don't `git add` it from main.

Sync happens automatically: every `git aim create` / `update` auto-commits and
pushes to `aim-sync`. For manual sync: `git aim sync` (runs pull/commit/push
inside `.aim/`).

Most commands are **git aliases** seeded by `git aim init`. If something breaks,
check `git config --get-regexp aim.alias` to debug.

## Commands

```bash
# List & filter
git aim list                          # open aims
git aim list -s "query" -o tree       # search + tree view

# Read
git aim get <ref>                     # details (-o json for structured)

# Create
git aim create -t "Title" -p 2                  # task (P2 = medium)
git aim create -t "Title" --epic init --dep init/1bm2  # with epic + dep

# Update
git aim update <ref> --status in_progress       # pick up
git aim update <ref> --status done              # close
git aim update <ref> --add-tag "pr:123"         # tag a PR
```

All commands support `-o json`. Run `git aim <cmd> --help` for full options.

## Aim References

- Epic: `init` — 4-char generated ID (only `misc` is pre-existing)
- Task: `init/1bm2` — epic/task, task ID is 4-char base-36
- Status: `open` | `in_progress` | `done` | `wont_do`
- Priority: `0` critical, `1` high, `2` medium, `3` low, `4` backlog

## Workflow

1. `git aim list` — see open aims
2. `git aim pickup <ref>` — (git alias) creates worktree + branch, sets status to in_progress
3. Work in the worktree at `.worktrees/<epic>/<task>.<slug>`
4. `git aim update <ref> --status done` — close when finished

### Worktrees

All work should be done in a git worktree. `git aim pickup <ref>` automates this:
- Creates branch `<epic>/<task>.<slug>` (e.g. `init/1bm2.implmnt-auth`)
- Creates worktree in `.worktrees/` (configurable via `git config aim.worktree-dir`)
- Tags the aim with `worktree:<branch>`
- Sets status to `in_progress`

## File Structure

```
.aim/aims/
├── 1b0.init/                    # epic directory (<id>.<slug>)
│   ├── README.md                # epic metadata + RFC design doc
│   ├── 1bm2.implmnt-auth.md    # task file (<id>.<slug>.md)
│   ├── 1bt9.fix-store.md       # each task ≈ 1 PR, ~2 min AI task
│   └── .archive/               # done/wont_do tasks moved here
│       └── 1bk7.old-task.md
├── 1bp.publish/
│   └── ...
└── 000.misc/                    # default epic for uncategorized tasks
```

- **Epic README.md**: contains epic metadata and RFC/design doc, typically
  created collaboratively by brainstorming with the user
- **Task files**: YAML frontmatter (status, priority, deps, tags) + markdown
  body. File naming (`<id>.<slug>.md`) is parsed by git-aim — don't rename
- **Archive**: completed tasks (`done`/`wont_do`) are moved to `.archive/`
  automatically
- **Conflicts**: since `.aim/` is a git worktree, resolve conflicts with
  `git -C .aim/ ...` (e.g. `git -C .aim/ merge --abort`)

## Conventions

- **Branches**: `<epic>/<task>.<slug>` (e.g. `1bd2/1bm2.implmnt-auth`)
- **Tags**: `worktree:<branch>`, `pr:<number>`
- **Dependencies**: aim refs in frontmatter (e.g. `dependencies: [init/1bm2]`)
