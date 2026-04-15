# `git aint new`

Create a new aint.

## Usage

```
git aint new --title "Fix auth redirect" [options]
```

## What it does

1. Generates a random base-36 ID (default 5 chars, configurable via `aint.id-length`).
2. Derives a slug from the title (or uses `--slug`).
3. Writes a markdown file with YAML frontmatter into `.aint/active/`.
4. Commits and pushes automatically (unless `--no-commit`/`--no-push`).

## File creation

New aints are always **file-form** — a single markdown file:

```
.aint/active/aint.{slug}.{id}.md
```

Example: `aint.fix-auth.ab12c.md`

### Creating child aints

Use `--in <parent_id>` to create a child inside an existing directory-form aint:

```
git aint new --title "Subtask" --in ab12c
```

This creates: `.aint/active/aint.parent-slug.ab12c/aint.subtask.ef56g.md`

The parent must already be a directory-form aint (have an `aint.md` inside its directory).
If not, you'll get an error asking you to convert it first.

## File format

```yaml
---
title: "Fix auth redirect"
status: open
priority: 2
---

Optional body text here.
```

## Flags

| Flag | Effect |
|------|--------|
| `--title <TEXT>` | **(required)** Title of the aint |
| `--description <TEXT>` | Inline body content |
| `--body-file <PATH>` | Read body from file (`-` for stdin) |
| `--in <REF>` | Create as child of parent aint |
| `--priority <0-4>` | 0=critical, 1=high, 2=medium (default), 3=low, 4=backlog |
| `--depends-on <REF...>` | Space-separated dependency IDs |
| `--slug <TEXT>` | Custom slug (default: auto-generated from title) |
| `--no-commit` | Skip auto-commit (implies `--no-push`) |
| `--no-push` | Skip auto-push |
| `--no-pull` | Skip auto-pull before writing |
| `--force` | Force operation |
| `--output json\|yaml\|table` | Output format |

## Slug generation

Slugs are auto-generated from the title:

- Tokenized on word boundaries
- Each token truncated to `aint.slug-token-len` chars (default: 8)
- At most `aint.slug-max-tokens` tokens (default: 3)
- Joined with hyphens

Example: "Implement OAuth2 authentication" becomes `impl-oauth2-auth`

## Safety

After writing, the file is checked against `.aint/.gitignore`.
If it would be ignored (and silently lost on commit), the file is removed and an error is shown.

## Example

```
$ git aint new --title "Add pagination to API" --priority 1
created [xy12z] .aint/active/aint.add-paginat-api.xy12z.md
```
