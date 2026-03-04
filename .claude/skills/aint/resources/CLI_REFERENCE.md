# CLI Reference

Essential commands for git-aint. All commands are invoked as `git aint <command>`.

## Core Commands

### create

Create a new aint.

```
Usage: git aint create [OPTIONS] --title <TITLE>
```

| Flag | Description | Default |
|------|-------------|---------|
| `--title <TITLE>` | Title (required) | |
| `--in <DIR>` | Parent directory slug (creates dir if needed) | `misc` |
| `--priority <PRIORITY>` | Priority: 0-4 | `2` |
| `--status <STATUS>` | Initial status | `open` |
| `--description <DESC>` | Description (markdown body) | |
| `--body-file <FILE>` | Read description from file (`-` for stdin) | |
| `--depends-on <DEPS>...` | Dependencies (aint IDs) | |
| `--slug <SLUG>` | Custom slug | |
| `--no-commit` | Skip auto-commit | |
| `--output <OUTPUT>` | Output format | `default` |

```bash
git aint create --title "Fix auth timeout"
git aint create --title "Add linting" --in ci-setup --priority1
git aint create --title "Maybe later" --status backlog
```

---

### get

Show full details of an aint.

```
Usage: git aint get [OPTIONS] <REFERENCE>
```

| Flag | Description | Default |
|------|-------------|---------|
| `--output <OUTPUT>` | Format: `default`, `wide`, `json`, `yaml` | `default` |
| `--format <FORMAT>` | Format string with `{placeholders}` | |
| `--no-body` | Skip the markdown body | |

**Format placeholders:** `{id}`, `{slug}`, `{dir}`, `{title}`,
`{status}`, `{priority}`, `{assignee}`, `{path}`, `{ref}`, `{tag:KEY}`,
`{config:KEY}`

```bash
git aint get c9x8                         # show details
git aint get c9x8 --output json                 # structured output
git aint get c9x8 --format "{tag:pr}"     # get PR number
```

---

### update

Update aint fields. Supports batch updates on multiple aints.

```
Usage: git aint update [OPTIONS] <REFERENCES>...
```

| Flag | Description |
|------|-------------|
| `--status <STATUS>` | Set status: `backlog`, `open`, `active`, `pushed`, `merged`, `rejected` |
| `--priority <PRIORITY>` | Set priority (0-4) |
| `--title <TITLE>` | Set title |
| `--assignee <ASSIGNEE>` | Set assignee |
| `--add-tag <TAGS>...` | Add tags (`key:value`) |
| `--rm-tag <TAGS>...` | Remove tags |
| `--add-dep <DEPS>...` | Add dependencies |
| `--rm-dep <DEPS>...` | Remove dependencies |
| `--slug <SLUG>` | Set new slug (renames file) |
| `--reason <REASON>` | Set reason (for rejected) |
| `--no-commit` | Skip auto-commit |
| `--output <OUTPUT>` | Output format |

```bash
git aint update c9x8 --status active             # start working
git aint update c9x8 --status pushed             # code pushed
git aint update c9x8 --status merged             # mark complete
git aint update c9x8 --add-tag "pr:42"           # link a PR
git aint update c9x8 d4m1 --status merged        # batch close
```

---

### pickup (alias)

Create worktree + branch, set status to active.

```
Usage: git aint pickup <REFERENCE>
```

```bash
git aint pickup c9x8
# → Branch:   ci-setup/c9x8.fix-auth
# → Worktree: .worktrees/ci-setup/c9x8.fix-auth/
# → Status:   active
# → Tags:     worktree:<path>, branch:<branch>
```

---

### summarize (alias)

Generate structured project status overview.

```
Usage: git aint summarize [DIR] [OPTIONS]
```

| Flag | Description | Default |
|------|-------------|---------|
| `--output <FORMAT>` | Output format: `txt`, `md` | `txt` |
| `--brief` | Compact one-line-per-aint output | |
| `[DIR]` | Scope to a specific directory slug | all dirs |

```bash
git aint summarize                        # txt, full detail
git aint summarize --brief                # txt, compact (for hooks)
git aint summarize --output md            # markdown (for auto-summary.md)
git aint summarize auth-rework            # single directory
```

**Aliases:** `summary`, `status`

---

## Other Commands

These are available but less commonly needed by AI agents:

| Command | Purpose |
|---------|---------|
| `list` | List/filter/search aints (`--status`, `--in`, `--search`, `--view tree`) |
| `doctor` | Health checks (`--fix` to auto-fix) |
| `sync` | Pull/commit/push manual changes in `.aint/` |
| `summarize` | Generate structured project status (`--output txt\|md`, `--brief`) |
| `summary` | Alias for `summarize` |
| `status` | Alias for `summary` |
| `push` | Push code, create PR via `gh`, set status to pushed |

Run `git aint <command> --help` for full syntax.

---

## Output Formats

All commands support `--output`:

| Format | Use Case |
|--------|----------|
| `default` | Human-readable terminal output |
| `json` | Programmatic parsing, AI agents |
| `yaml` | Human-readable structured data |

**For AI agents**, use `--output json` for reliable parsing.
