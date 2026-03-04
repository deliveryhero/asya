---
description: Show full details of an aint
argument-hint: "<reference>"
---

Show full details of a single aint. Supports structured output and custom
format strings with placeholders.

## Usage

```bash
git aint get [OPTIONS] <REFERENCE>
```

The reference can be a bare 4-char ID (e.g. `c9x8`) or a file path (e.g. `.aint/aints/ci-setup/active.c9x8.fix-auth.md`).

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--output <OUTPUT>` | Format: `default`, `wide`, `json`, `yaml` | `default` |
| `--format <FORMAT>` | Format string with `{placeholders}` (see below) | |
| `--no-body` | Skip the markdown body | |

**Format placeholders:** `{id}`, `{slug}`, `{dir}`, `{title}`,
`{status}`, `{priority}`, `{assignee}`, `{path}`, `{ref}`, `{tag:KEY}`,
`{config:KEY}`

## Examples

```bash
git aint get c9x8                         # show aint details
git aint get c9x8 --output json                 # structured JSON output
git aint get c9x8 --format "{status}"     # just the status
git aint get c9x8 --format "{tag:pr}"     # get PR number tag
```
