---
description: Create a new aint
argument-hint: "--title <title>"
---

Create a new aint. Auto-commits and pushes to `aint-sync` by default.

## Usage

```bash
git aint create [OPTIONS] --title <TITLE>
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--title <TITLE>` | Title (required) | |
| `--in <DIR>` | Parent directory slug (creates dir if needed) | `misc` |
| `--priority <PRIORITY>` | Priority: 0-4 | `2` |
| `--status <STATUS>` | Initial status | `open` |
| `--description <DESC>` | Description (markdown body, inline) | |
| `--body-file <FILE>` | Read description from file (`-` for stdin) | |
| `--depends-on <DEPS>...` | Dependencies (aint IDs) | |
| `--slug <SLUG>` | Custom slug (default: auto-generated) | |
| `--no-commit` | Skip auto-commit and auto-push | |
| `--no-push` | Skip auto-push after commit | |
| `--output <OUTPUT>` | Output format | `default` |

## Examples

```bash
# Create aint (default dir: misc, default status: open)
git aint create --title "Fix authentication timeout"

# Create in a specific dir
git aint create --title "Add linting step" --in ci-setup

# Create with priority and deps
git aint create --title "Add tests" --in ci-setup --priority 1 --depends-on c9x8

# Create as backlog
git aint create --title "Maybe later" --status backlog
```
