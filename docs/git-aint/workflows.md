# Workflows

End-to-end guides for common git-aint workflows.

## Starting a new feature

Plan a feature as a directory-form parent aint with child aints for each piece of
work. This gives you composition (parent/child via nesting) and dependencies
(ordering via frontmatter).

**1. Create the parent aint:**

```bash
git aint new --title "API rate limiting"
```

This creates a file-form aint. To make it directory-form (so it can hold children
and supporting documents), convert it by hand: create the directory, move the file
to `aint.md` inside it, and sync.

Or plan ahead by creating the parent, then adding children with `--in`:

```bash
# Create the parent
git aint new --title "API rate limiting"
# created [k8m2p] .aint/active/aint.api-rate-limiting.k8m2p.md
```

**2. Add child aints with dependencies:**

```bash
# First child: design the token bucket algorithm
git aint new --title "Design token bucket algorithm" --in k8m2p

# Second child: implement the middleware (depends on the design)
git aint new --title "Implement rate limit middleware" --in k8m2p --depends-on r3x9w

# Third child: add integration tests (depends on the implementation)
git aint new --title "Integration tests for rate limiting" --in k8m2p --depends-on f7n1q
```

**3. Review the plan:**

```bash
# Tree view shows parent/child hierarchy
git aint get -o tree

# Detail view shows deps, blockers, and unblocks
git aint get k8m2p -o detail
```

**4. Start working:**

```bash
# Find unblocked work
git aint whats-next

# Pick up the first unblocked child
git aint pickup r3x9w
```

## Quick bug fix

For a simple bug that does not need children or an RFC, the cycle is:
create, pickup, work, push, merge.

```bash
# 1. Create the aint
git aint new --title "Fix null pointer in auth middleware" --priority 1
# created [ab12c] .aint/active/aint.fix-null-pointer-auth-middleware.ab12c.md

# 2. Pick it up (creates worktree + branch, sets status to working)
git aint pickup ab12c
# Picked up [ab12c] in /repo/.worktrees/ab12c.fix-null-pointer-auth-middleware

# 3. Work in the worktree
cd .worktrees/ab12c.fix-null-pointer-auth-middleware
# ... edit files, run tests ...
git add -A && git commit -m "Fix null deref in auth middleware"

# 4. Push and create a PR
git push -u origin ab12c.fix-null-pointer-auth-middleware

# 5. Tag the aint with the PR number
git aint set ab12c --status pushed --add-tag "pr:142"

# 6. After the PR is merged
git aint set ab12c --status merged

# 7. Clean up the worktree
git aint cleanup
```

## Managing dependencies

Dependencies express ordering constraints between aints. They live in the
frontmatter `dependencies` field and reference other aints by bare ID.

**Add a dependency:**

```bash
git aint set f7n1q --add-dep r3x9w
```

This means `f7n1q` is blocked by `r3x9w` -- it cannot proceed until `r3x9w`
is closed (merged or rejected).

**Remove a dependency:**

```bash
git aint set f7n1q --rm-dep r3x9w
```

**Find unblocked work:**

```bash
# Aints where all deps are closed (or no deps at all)
git aint get --deps clear

# Aints that are blocked by at least one open dependency
git aint get --deps blocked

# Aints that have at least one dependency (regardless of status)
git aint get --deps any

# Aints with no dependencies at all
git aint get --deps none
```

**Combine with status filters:**

```bash
# Open aints that are ready to pick up (unblocked)
git aint get --status open --deps clear

# Or use the alias
git aint whats-next
```

**View the dependency graph:**

```bash
# Tree output shows the full hierarchy
git aint get -o tree

# Detail view for one aint shows blockers and what it unblocks
git aint get f7n1q -o detail
```

Cycle detection runs automatically whenever you add a dependency. If adding a dep
would create a circular dependency, the command fails with an error.

## Searching and filtering

git-aint supports text search, file search, and structured filters. All filters
can be combined.

**Full-text search (title and body):**

```bash
# Search for "auth" in titles and bodies (OR logic by default)
git aint get -s "auth"

# AND logic: all words must match
git aint get -S "auth redirect"
```

**Search inside directory files:**

```bash
# Search inside rfc.md, adr.*.md, and other files in aint directories
git aint get --search-files "*.md" -s "token bucket"
```

**Filter by status:**

```bash
git aint get --status open
git aint get --status working pushed
git aint get --status closed          # shortcut: merged + rejected
git aint get --status all             # everything
```

**Filter by priority:**

```bash
git aint get --priority 0             # critical only
git aint get --priority 1             # high priority
```

**Filter by tag:**

```bash
git aint get --tag "pr:142"
git aint get --tag "branch:ab12c.fix-auth"
```

**Filter by assignee:**

```bash
git aint get --assignee "alice"
```

**Filter by parent (directory):**

```bash
git aint get --in k8m2p               # children of a specific parent
```

**Combine filters:**

```bash
# Open, high-priority aints assigned to me that are unblocked
git aint get --status open --priority 1 --assignee "alice" --deps clear

# Search within a specific parent's children
git aint get --in k8m2p -s "middleware"
```

**Limit results:**

```bash
git aint get --limit 5
```

**Include related aints:**

```bash
git aint get k8m2p --with children     # show children
git aint get f7n1q --with dependants   # show aints that depend on this
git aint get f7n1q --with blockers     # show aints blocking this
```

## PR workflow

The `pr` tag links an aint to a GitHub pull request. This is not enforced by
git-aint -- it is a convention you apply with `--add-tag`.

**Tag an aint with a PR:**

```bash
git aint set ab12c --status pushed --add-tag "pr:142"
```

**Find the aint for a PR:**

```bash
git aint get --tag "pr:142"
```

**Find the aint for a branch:**

```bash
git aint get --tag "branch:ab12c.fix-auth"
```

**Typical status transitions with PRs:**

```bash
# After pushing and opening the PR
git aint set ab12c --status pushed --add-tag "pr:142"

# After the PR is merged on GitHub
git aint set ab12c --status merged

# Clean up worktree and branch
git aint cleanup
```

**Extract the PR number programmatically:**

```bash
git aint get ab12c --format "{tag:pr}"
# 142
```

## Direct file editing

Aints are plain markdown files with YAML frontmatter. You can always edit them
directly with any text editor. This is by design -- git-aint is hackable.

**Read an aint file:**

```bash
# Find the path
git aint get ab12c --format "{path}"
# active/aint.fix-auth.ab12c.md

# Open it
vim .aint/active/aint.fix-auth.ab12c.md
```

**Or use the built-in editor integration:**

```bash
git aint set ab12c --editor
git aint set ab12c --editor=vim
```

**Edit frontmatter by hand:**

Open the file and change any field. The frontmatter is standard YAML:

```yaml
---
title: "Fix auth redirect"
status: working
priority: 1
assignee: "alice"
dependencies: [r3x9w]
tags:
  - pr:142
  - worktree:.worktrees/ab12c.fix-auth
  - branch:ab12c.fix-auth
---

The auth redirect is broken when the session cookie expires.
```

**Sync after manual edits:**

After editing files by hand, sync to commit and push:

```bash
git aint sync
```

Use `--dry-run` to preview what would be committed:

```bash
git aint sync --dry-run
```

**Validate after editing:**

```bash
git aint doctor
```

This checks frontmatter validity, broken references, orphaned files, and more.
Use `--fix` to auto-repair safe issues.

**Add supporting files to a directory-form aint:**

Directory-form aints can hold any extra files -- RFCs, ADRs, notes, diagrams.
Just create the file in the aint's directory:

```bash
vim .aint/active/aint.api-rate-limiting.k8m2p/rfc.md
git aint sync
```

Remove a supporting file:

```bash
git aint rm k8m2p --file rfc.md
```

## Batch operations

The `set` command accepts multiple references, so you can update several aints
at once.

**Set status on multiple aints:**

```bash
git aint set ab12c ef56g hi78j --status merged
```

**Add a tag to multiple aints:**

```bash
git aint set ab12c ef56g --add-tag "sprint:12"
```

**Reprioritize a batch:**

```bash
git aint set ab12c ef56g hi78j --priority 1
```

**Structured output for scripting:**

Use `--output json` or `--output yaml` to get machine-readable output from any
command. Use `--format` for custom templates.

```bash
# List all open aint IDs
git aint get --status open --output json | jq -r '.[].id'

# Custom format: just ID and title
git aint get ab12c --format "{id} {title}"

# Get a specific tag value
git aint get ab12c --format "{tag:worktree}"
```

**Shell loops for bulk operations:**

```bash
# Close all pushed aints
for id in $(git aint get --status pushed --output json | jq -r '.[].id'); do
  git aint set "$id" --status merged
done

# Add a tag to all aints in a directory
for id in $(git aint get --in k8m2p --output json | jq -r '.[].id'); do
  git aint set "$id" --add-tag "milestone:v2"
done
```
