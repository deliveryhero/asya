# Statuses

Only aints have statuses. Supporting files (rfc.md, adr.*.md, etc.) are
free-format and have no status.

## The five statuses

| Status | Abbrev | Directory | Meaning |
|--------|--------|-----------|---------|
| `open` | `o` | `active/` | Ready to be picked up |
| `working` | `w` | `active/` | Someone is actively working on it |
| `pushed` | `p` | `active/` | Branch pushed or PR open |
| `merged` | `m` | `archive/` | Completed and merged |
| `rejected` | `r` | `archive/` | Closed without completing |

## Active vs archived

A status is either **active** or **closed**:

- **Active** (`open`, `working`, `pushed`) — the aint file lives in `.aint/active/`.
- **Closed** (`merged`, `rejected`) — the aint file lives in `.aint/archive/`.

When you change an aint's status between active and closed, the file (or entire
directory for dir-form aints) is physically moved:

```
# closing:  active/ -> archive/
git aint set ab12c --status merged

# reopening: archive/ -> active/
git aint set ab12c --status open
```

For child aints nested inside a parent, closing moves them to a mirror of the
parent directory under `archive/`:

```
active/aint.parent.ab12c/aint.child.ef56g.md
  -> archive/aint.parent.ab12c/aint.child.ef56g.md
```

## Lifecycle

```
open -> working -> pushed -> merged
                          \-> rejected
```

There are no enforced transitions — you can set any status at any time.
The flow above is the typical progression.

## Filtering by status

```bash
git aint get                          # active only (default)
git aint get --status open            # just open
git aint get --status working pushed  # multiple
git aint get --status closed          # shortcut for merged + rejected
git aint get --status all             # everything
git aint get --status-group archive   # same as --status closed
```

## Priority is not a status

Priority (`--priority 0-4`) is a separate field. Priority 4 is labeled "backlog"
but `backlog` is not a status value — there is no `backlog` status.
