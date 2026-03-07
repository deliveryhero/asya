# Patterns

Common usage patterns for AI agents working with git-aint.

## Creating Aints

### Capture the reference from create output

```bash
# Use --output json to reliably parse the created aint's reference
git aint create --title "Implement feature" --in ci-setup --priority 2 --output json
```

The JSON output includes the `id` field (e.g. `c9x8`) which you need
for subsequent operations.

### Create with all metadata upfront

```bash
git aint create --title "Add OAuth support" \
  --in ci-setup \
  --priority 1 \
  --depends-on c9x8 \
  --description "Implement OAuth 2.0 flow with Google and GitHub providers" \
  --output json
```

---

## Status Lifecycle

```
backlog → open → active → pushed → merged
                        ↘ rejected
```

| Status | Meaning | How to set |
|--------|---------|------------|
| `backlog` | Untriaged idea | `--status backlog` on create |
| `open` | Triaged, ready for work | Default on create |
| `active` | Work in progress | `git aint pickup <ref>` or `update --status active` |
| `pushed` | Code pushed, PR open | `git aint update <ref> --status pushed` |
| `merged` | Complete, PR merged | `git aint update <ref> --status merged` |
| `rejected` | Won't implement | `git aint update <ref> --status rejected --reason "..."` |

### Transition examples

```bash
# Pick up for work (open → active), creates worktree
git aint pickup c9x8

# Code pushed (active → pushed)
git aint update c9x8 --status pushed

# Mark complete (pushed → merged)
git aint update c9x8 --status merged

# Reject (any → rejected)
git aint update c9x8 --status rejected --reason "No longer needed"
```

---

## Tagging PRs and Worktrees

Tags are `key:value` pairs stored in the aint's frontmatter.

```bash
# Link a PR
git aint update c9x8 --add-tag "pr:42"

# Find the aint for a PR
git aint list --tag "pr:42"

# Show tag values in list
git aint list --columns "tag:pr"

# Remove a tag
git aint update c9x8 --rm-tag "pr:42"
```

---

## Common Agent Patterns

### Session start: check what is open

```bash
git aint list --output json                  # get all open aints
git aint status                        # quick summary
```

### Before starting work: pick up an aint

```bash
git aint pickup c9x8                   # creates worktree, sets active
```

### After creating a PR: tag the aint

```bash
git aint update c9x8 --add-tag "pr:42" --status pushed
```

### After merging: mark complete

```bash
git aint update c9x8 --status merged
```

### Finding related work

```bash
git aint list -s "auth" --output json         # substring search
git aint list -S -s "auth migration"          # all words must match (AND)
git aint list -S -s "design" --search-files "*.md"  # also search rfc.md etc.
git aint list --view tree                     # dependency tree view
```

### Batch operations

```bash
git aint update c9x8 d4m1 --status merged          # close multiple
git aint update c9x8 d4m1 --priority 1              # set priority on multiple
```

### Direct file access

The source of truth is the files in `.aint/` — you can read or edit them
directly instead of using CLI commands:

```bash
# Read an aint file directly
cat .aint/aints/ci-setup/active.c9x8.fix-auth.md

# Edit frontmatter or body directly
# (rename file to change status: open.* → active.*)

# After manual edits, sync or validate:
git aint sync                          # commit + push
git aint doctor                        # check for problems
```
