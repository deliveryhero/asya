---
description: Update aint fields (status, priority, deps, tags)
argument-hint: "<references>..."
---

Update one or more aint fields: status, priority, tags, dependencies, slug,
and more. Supports batch updates on multiple aints at once.

## Usage

```bash
git aint update [OPTIONS] <REFERENCES>...
```

## Options

| Flag | Description |
|------|-------------|
| `--status <STATUS>` | Set status: `backlog`, `open`, `active`, `pushed`, `merged`, `rejected` |
| `--priority <PRIORITY>` | Set priority (0-4) |
| `--title <TITLE>` | Set title |
| `--assignee <ASSIGNEE>` | Set assignee |
| `--add-tag <TAGS>...` | Add tags (`key:value`) |
| `--rm-tag <TAGS>...` | Remove tags |
| `--add-dep <DEPS>...` | Add dependencies (aint IDs) |
| `--rm-dep <DEPS>...` | Remove dependencies |
| `--slug <SLUG>` | Set new slug (renames file) |
| `--reason <REASON>` | Set reason (e.g. for rejected) |
| `--editor [<EDITOR>]` | Open in editor |
| `--no-commit` | Skip auto-commit and auto-push |
| `--no-push` | Skip auto-push after commit |
| `--output <OUTPUT>` | Output format |

## Examples

```bash
# Status transitions
git aint update c9x8 --status active             # start working
git aint update c9x8 --status pushed             # code pushed / PR open
git aint update c9x8 --status merged             # mark complete

# Tagging
git aint update c9x8 --add-tag "pr:42"           # link a PR

# Batch update
git aint update c9x8 d4m1 --status merged        # close multiple

# Reject with reason
git aint update c9x8 --status rejected --reason "Superseded by new design"
```
