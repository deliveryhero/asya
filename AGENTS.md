# git-aint: Agent Instructions

This project uses **git-aint** for issue tracking.

## How It Works

Aints (issues) are markdown files with YAML frontmatter stored in `.aint/aints/`.
The `.aint/` directory is a **git worktree** on the `aint-sync` branch — it's
gitignored from the main branch. Don't `git add` it from main.

**The source of truth is the files in `.aint/`.** You can read, edit, create, or
delete aint files directly — they're just markdown. After manual edits, run
`git aint sync` to commit and push, or `git aint doctor` to validate.

The CLI (`git aint create`, `update`, etc.) auto-commits and pushes to `aint-sync`
after each write operation. For manual sync: `git aint sync` (runs pull/commit/push
inside `.aint/`).

## Commands

```bash
# List & filter
git aint list                          # open aints
git aint list --search "query" --view tree  # search + tree view
git aint list --stats                  # summary statistics

# Read
git aint get <ref>                     # details (--output json for structured)

# Create
git aint create --title "Title" --priority 2            # aint (P2 = medium)
git aint create --title "Title" --in ci-setup           # in a specific dir

# Update
git aint update <ref> --status active          # pick up
git aint update <ref> --status pushed          # code pushed
git aint update <ref> --status merged          # close
git aint update <ref> --add-tag "pr:123"       # tag a PR

# Health checks
git aint doctor                        # run all validation checks
git aint doctor --fix                  # auto-fix safe issues
git aint doctor --only sync            # check .aint/ sync status
```

All commands support `--output json`. Run `git aint <cmd> --help` for full options.

## Aint References

- Aint ID: `c9x8` — 4-char base-36 random ID
- File path: `.aint/aints/ci-setup/active.c9x8.fix-auth.md` (also accepted)
- Status: `backlog` | `open` | `active` | `pushed` | `merged` | `rejected`
- Priority: `0` critical, `1` high, `2` medium, `3` low, `4` backlog

## Workflow

1. `git aint list` — see open aints
2. `git aint pickup <ref>` — (alias) creates worktree + branch, sets status to active
3. Work in the worktree
4. `git aint push <ref>` — push code, create PR, set status to pushed
5. `git aint update <ref> --status merged` — close when PR merged

### Worktrees

All work should be done in a git worktree. `git aint pickup <ref>` automates this:
- Creates branch `<epic>/<task>.<task_slug>` (e.g. `{epic}/{task}.{task_slug}`)
- Creates worktree in `.worktrees/` (configurable via `git config aint.worktree-dir`)
- Tags the aint with `worktree:<path>` and `branch:<branch>`
- Sets status to `active`

## File Structure

```
.aint/aints/
├── .closed/                         # closed dirs (moved here when done)
│   └── old-feature/
│       ├── summary.md
│       └── merged.a3x1.impl-thing.md
├── ci-setup/                        # grouping dir (slug only, no ID)
│   ├── summary.md                   # dir metadata (title + description)
│   ├── rfc.md                       # optional RFC/design doc
│   ├── .closed/                     # closed aints within the dir
│   │   └── merged.b2k9.fix-pipe.md
│   ├── active.c9x8.fix-auth.md     # aint file: <status>.<id>.<slug>.md
│   └── open.d4m1.add-cache.md
├── misc/                            # default dir
│   └── backlog.e5n2.random-idea.md
└── open.f6p3.standalone-task.md     # aint at root (no dir)
```

- **summary.md**: dir metadata (title + description). No status field — dirs
  are open (in `aints/`) or closed (moved to `aints/.closed/`)
- **rfc.md**: optional RFC/design doc
- **Aint files**: YAML frontmatter (priority, deps, tags) + markdown body.
  Status is encoded in the filename (`<status>.<id>.<slug>.md`). Closed
  aints are moved to `.closed/` within their directory
- **Conflicts**: since `.aint/` is a git worktree, resolve conflicts with
  `git -C .aint/ ...` (e.g. `git -C .aint/ merge --abort`)

## Conventions

- **Branches**: `<epic>/<task>.<task_slug>` (e.g. `{epic}/{task}.{task_slug}`)
- **Tags**: `worktree:<path>`, `branch:<branch>`, `pr:<number>`
- **Dependencies**: aint IDs in frontmatter (e.g. `dependencies: [c9x8, d4m1]`)
