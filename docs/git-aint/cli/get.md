# `git aint get`

Show details of an aint, or list/search aints when no reference is given.

## Usage

```
git aint get [<ref>] [options]
```

## Modes

### Single-aint mode

When a reference is given with `-o detail` or `--format`:

```
git aint get ab12c -o detail
git aint get ab12c --format "{id} {title} {status}"
```

Shows full aint metadata: title, status, priority, assignee, tags, dependencies, body.
Use `--no-body` to suppress the body text.

### List mode (default)

When no reference is given, or with filtering flags:

```
git aint get                          # all active aints
git aint get --status open            # only open
git aint get --status working pushed  # multiple statuses
git aint get -s "auth"                # search titles and body
```

## Filtering

### By status

```
git aint get --status open            # single status
git aint get --status open working    # multiple
git aint get --status closed          # shortcut for merged + rejected
git aint get --status all             # everything
```

Status aliases: `o` (open), `w` (working), `p` (pushed), `m` (merged), `r` (rejected).

Running `--status` with no value prints available status values.

### By status group

```
git aint get --status-group active    # default: open + working + pushed
git aint get --status-group archive   # merged + rejected
git aint get --status-group all       # everything
```

### By dependency state

```
git aint get --deps clear    # unblocked (all deps closed or no deps)
git aint get --deps blocked  # at least one dep not closed
git aint get --deps any      # has at least one dependency
git aint get --deps none     # no dependencies at all
```

### By other fields

```
git aint get --priority 0             # critical only
git aint get --assignee "Alice"       # by assignee
git aint get --tag "pr:401"           # by tag
git aint get --in ab12c              # children of parent aint
git aint get --limit 5                # limit results
```

## Search

### Text search

```
git aint get -s "auth redirect"       # matches if string appears in title or body
git aint get -s "auth redirect" -S    # --split: ALL words must match (AND logic)
```

### File search

```
git aint get --search-files "rfc.md"  # also search matching files in aint directories
git aint get --search-files "*.md"    # glob patterns supported
```

This searches inside each directory-form aint for files matching the glob,
and includes their content in the search. Useful for finding aints by content
in supporting documents like RFCs or ADRs.

## Related aints

```
git aint get ab12c --with children    # show child aints
git aint get ab12c --with dependants  # aints that depend on this one
git aint get ab12c --with blockers    # aints this one depends on
git aint get ab12c --with blockers --depth 2  # limit traversal depth
```

## Output formats

| Format | Flag | Description |
|--------|------|-------------|
| table | `-o table` | Default. Colored table: ID, TITLE, STATUS, PRI |
| wide | `-o wide` | More columns, full paths, full titles |
| detail | `-o detail` | Full metadata with body |
| tree | `-o tree` | Dependency tree visualization |
| files | `-o files` | Filesystem tree with metadata |
| json | `-o json` | Structured JSON export |
| yaml | `-o yaml` | YAML serialization |
| custom | `--format "..."` | Template string |

### Extra columns

```
git aint get --columns assignee deps tags
git aint get --columns tag:worktree tag:pr   # specific tag values
```

### Template placeholders

For `--format`:

`{id}`, `{slug}`, `{dir}`, `{dir_slug}`, `{title}`, `{status}`, `{priority}`,
`{assignee}`, `{path}`, `{ref}`, `{tag:KEY}`, `{config:KEY}`

### Summary modes

```
git aint get --stats              # totals by status, tasks per directory
git aint get --summary-line       # prepend one-line header
```

## Examples

```
$ git aint get
ID      TITLE                           STATUS    PRI
ab12c   Fix auth redirect               working     1
ef56g   Add pagination to API           open        2

$ git aint get ab12c --format "{id} {tag:worktree}"
ab12c .worktrees/ab12c.fix-auth

$ git aint get -s "auth" --search-files "rfc.md"
ID      TITLE                           STATUS    PRI
ab12c   Fix auth redirect               working     1
```
