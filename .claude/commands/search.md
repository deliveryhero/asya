---
description: Search and filter aints
argument-hint: "--search <query>"
---

Search and filter aints using full-text search, status, directory, priority,
tags, and more. Wraps `git aint list` with common filter options.

## Usage

```bash
git aint list [OPTIONS]
```

## Filter Options

| Flag | Description |
|------|-------------|
| `--search <QUERY>` | Full-text search across titles and body |
| `--status [<STATUS>...]` | Filter by status (e.g. `--status open active`) |
| `--in <DIR>` | Filter by directory (e.g. `--in ci-setup`) |
| `--priority <PRIORITY>` | Filter by priority (0-4) |
| `--assignee <ASSIGNEE>` | Filter by assignee |
| `--tag <TAG>` | Filter by tag (`key:value`) |
| `--deps <FILTER>` | Filter by dependency status: `clear`, `blocked`, `any`, `none` |

## Display Options

| Flag | Description |
|------|-------------|
| `--view <VIEW>` | Layout: `flat`, `tree`, `deps`, `rdeps` |
| `--columns <COLS>...` | Extra columns: `assignee`, `deps`, `tags`, `tag:<key>` |
| `--limit <N>` | Limit number of results |
| `--summary-line` | Prepend a summary header line |
| `--stats` | Show summary statistics only |
| `--output <FORMAT>` | Output format: `default`, `wide`, `json`, `yaml` |

## Examples

```bash
# Full-text search
git aint list --search "authentication"

# Filter by status
git aint list --status active                  # in progress
git aint list --status open active             # multiple statuses

# Filter by directory
git aint list --in ci-setup

# Find aint for a PR
git aint list --tag "pr:42"

# Combine filters
git aint list --in ci-setup --status active --priority 1

# Dependency views
git aint list --view tree                      # grouped tree view
git aint list --deps blocked                   # only blocked aints

# Structured output for parsing
git aint list --output json
```
