# File structure

Everything lives in `.aint/`, which is a git worktree on the orphan `aint-sync`
branch. It's gitignored from your main branch — aint data never mixes with
source code.

## Directory layout

```
.aint/
  active/                               # open/working/pushed aints
    aint.fix-auth.ab12c.md              # file-form aint
    aint.gateway-rearch.ef56g/          # directory-form aint
      aint.md                           #   aint metadata
      rfc.md                            #   supporting document
      aint.strip-pg.cd34h.md            #   child aint (file-form)
      aint.add-cache.gh78i/             #   child aint (dir-form)
        aint.md
  archive/                              # merged/rejected aints (same structure)
    aint.done-task.jk90l.md
    aint.gateway-rearch.ef56g/          # mirror of parent dir for closed children
      aint.finished-child.mn12o.md
  scripts/                              # shell scripts for aliases
    pickup.sh
    worktree.sh
    tmux.sh
    md/                                 # static markdown files
      just-a-tool.md
  docs/                                 # static reference docs
  trash/                                # ephemeral scratch (plans, notes)
  auto_state.md                         # auto-generated project state
  AGENTS.md                             # agent instructions
  .gitignore                            # managed by init
  .gitattributes                        # merge driver config
```

## What's tracked on `aint-sync`

The `.aint/.gitignore` uses an allowlist — everything is ignored except:

```
active/   archive/   scripts/   docs/   trash/
auto_state.md   AGENTS.md   .gitignore
```

This means you can drop scratch files in `.aint/` and they won't be committed
unless they're inside one of the tracked directories.

## Aint files

Only aint files have IDs. Everything else (rfc.md, adr.*.md, etc.) is free-format.

### File-form

A standalone markdown file. Name format: `aint.{slug}.{id}.md`

```
aint.fix-auth.ab12c.md
```

Three dot-separated segments: `aint` prefix, slug, ID. The `.md` suffix is required.
Slugs use hyphens (never dots), so splitting on `.` is unambiguous.

### Directory-form

A directory containing `aint.md` plus optional supporting files and children.
Name format: `aint.{slug}.{id}/`

```
aint.gateway-rearch.ef56g/
  aint.md            # the aint itself (required)
  rfc.md             # supporting document (optional, free-format)
  adr.nats.md        # another supporting doc
  aint.child.gh78i.md  # child aint
```

The directory name follows the same `aint.{slug}.{id}` pattern but without `.md`.
Inside, `aint.md` is the aint's metadata file — its ID comes from the parent
directory name, not the filename.

### Converting between forms

There's no built-in command to convert file-form to directory-form. Do it manually:

```bash
cd .aint/active
mkdir aint.my-task.ab12c
mv aint.my-task.ab12c.md aint.my-task.ab12c/aint.md
git aint sync
```

## Frontmatter format

Every aint file starts with YAML frontmatter between `---` delimiters:

```yaml
---
title: Fix auth redirect
status: open
priority: 2 # medium
assignee: alice
tags:
  - pr:401
  - worktree:.worktrees/ab12c.fix-auth
  - branch:ab12c.fix-auth
dependencies:
  - cd34e
  - fg56h
reason: superseded by new design
---

Markdown body starts here. This is free-form content.
```

### Required fields

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `title` | string | *(required)* | Auto-quoted if it contains YAML-special characters (`:`, `[`, `#`, etc.) |
| `status` | string | `open` | One of: `open`, `working`, `pushed`, `merged`, `rejected` |
| `priority` | integer | `2` | 0-4. Written with a comment: `2 # medium` |

### Optional fields

| Field | Type | Notes |
|-------|------|-------|
| `assignee` | string | Free-text name. Auto-set to `git config user.name` on `--status working` |
| `tags` | list of `key:value` | Arbitrary. Some keys have special meaning (see below) |
| `dependencies` | list of IDs | Bare 5-char aint IDs |
| `reason` | string | Why status changed (e.g., rejection reason) |

### Body

Everything after the closing `---` is the body. It's free-form markdown.
An empty body is valid — the closing `---` is immediately followed by EOF.

### Tags

Tags are `key:value` strings. Any key is allowed. Some have special meaning:

| Key | Set by | Value |
|-----|--------|-------|
| `worktree` | `pickup` alias | Relative path from repo root (e.g., `.worktrees/ab12c.fix-auth`) |
| `branch` | `pickup` alias | Git branch name (e.g., `ab12c.fix-auth`) |
| `pr` | User or CI | GitHub PR number (e.g., `401`) |

### Dependencies

Bare aint IDs (e.g., `cd34e`). Dependencies are cross-directory — any aint can
depend on any other aint regardless of where they live in the filesystem.

## IDs

- Base-36 lowercase: `[0-9a-z]`
- Length: 5-10 chars (configurable via `git config aint.id-length`, default 5)
- Randomly generated, collision-checked against existing IDs
- 5 chars = 36^5 = ~60 million possibilities

## Slugs

- Auto-generated from title by tokenizing on word boundaries
- Token length: `aint.slug-token-len` (default: 8 chars per token)
- Max tokens: `aint.slug-max-tokens` (default: 3)
- Hyphens between tokens, never dots
- Example: "Implement OAuth2 authentication" → `impl-oauth2-auth`
- Can be overridden with `--slug` on create, or changed with `git aint set --slug`

## Supporting files

Files inside a directory-form aint that aren't aints themselves. These have no
IDs and no required format. Common conventions:

| Pattern | Purpose |
|---------|---------|
| `rfc.md` | Request for comments / design doc |
| `rfc.{slug}.md` | Named RFC |
| `adr.{slug}.md` | Architecture decision record |
| `scenario.{slug}.md` | Usage scenario |
| `research.{slug}.md` | Research notes |

These are recognized by `doctor` and shown in `auto_state.md`, but the naming
is purely conventional — any file works.

## Child aints and nesting

Child aints live inside a parent's directory. They can be file-form or dir-form:

```
aint.parent.ab12c/
  aint.md                    # parent
  aint.child-a.ef56g.md      # file-form child
  aint.child-b.gh78i/        # dir-form child
    aint.md
```

When a child is closed, it moves to `archive/` under a mirror of the parent
directory name:

```
archive/aint.parent.ab12c/aint.child-a.ef56g.md
```

This preserves the parent relationship in the archive.

## `active/` vs `archive/`

The directory an aint lives in reflects its status:

- `active/` — statuses `open`, `working`, `pushed`
- `archive/` — statuses `merged`, `rejected`

`git aint set --status merged` physically moves the file/directory.
This is the only thing that determines location — there's no separate index.

## Hackability

The entire data model is plain files and YAML. You can:

- **Edit files directly** — any text editor works. Run `git aint sync` after.
- **Script with standard tools** — `grep`, `yq`, `find`, shell loops.
- **Bulk operations** — edit multiple files, then `git aint sync` once.
- **Custom fields** — unknown YAML fields are preserved on read (serde's default
  behavior) but not written back by `git aint set`. Edit manually if needed.
- **Git operations** — `cd .aint && git log`, `git diff`, `git blame` all work
  since it's a normal git worktree.

The only assumption the CLI makes: filenames follow the `aint.{slug}.{id}.md`
pattern, and the frontmatter has at least a `title:` field. Everything else
has sensible defaults.
