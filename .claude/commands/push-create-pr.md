---
description: Push branch to origin and create/update a GitHub PR
argument-hint: "<reference> [--title <text>] [--description <text>]"
---

Push the aint's branch to origin and create a GitHub PR (or update existing).
Requires `gh` CLI installed. Sets status to `pushed` and tags with `pr:<number>`.

## Usage

```bash
git aint push <REFERENCE> [--title <text>] [--description <text>]
```

## What it does

1. Validates aint is not already closed
2. Pushes branch to origin
3. If PR exists: tags aint with pr number, done
4. If no PR: creates one with title from `aint.pr-title-pattern` config
5. Sets status to `pushed`, tags with `pr:<number>`

## Examples

```bash
git aint push c9x8                          # push and create PR
git aint push c9x8 --title "Fix auth bug"  # custom PR title
git aint push c9x8 --description "Details" # add PR body text
```
