# `git aint doctor`

Run health checks, validation, and cleanup on your aints.

## Usage

```
git aint doctor [<ref>] [options]
```

## What it does

Runs a suite of checks against your aint data and infrastructure. With `--fix`,
automatically resolves safe issues.

## Flags

| Flag | Effect |
|------|--------|
| `<REF>` | Scope checks to a single aint |
| `--all` | Include closed aints (default: active only) |
| `--fix` | Auto-fix safe issues and perform cleanup |
| `--no-commit` | Skip auto-commit after fixing |
| `--only <CHECKS...>` | Run only named checks (comma-separated) |
| `--skip <CHECKS...>` | Skip named checks (comma-separated) |
| `-o\|--output json\|yaml\|table` | Output format |

## Checks

### Validation checks (run by default)

| Check | What it does |
|-------|--------------|
| `aint-worktree` | Verifies `.aint/` worktree exists and is valid |
| `legacy-dir` | Detects legacy directory structures |
| `file-naming` | Validates aint file/directory naming conventions |
| `status-migration` | Detects aints needing status migration |
| `parsing` | Parses YAML frontmatter, checks required fields (title, status, priority) |
| `references` | Checks dependency references resolve to existing aints |
| `orphaned-refs` | Finds aints with dangling parent references |
| `cycles` | Detects dependency cycles |
| `prs` | Checks PR tags against GitHub state |
| `worktrees` | Validates worktree tags point to existing directories |
| `aint-duplicates` | Finds duplicate IDs |
| `id-length` | Checks IDs match configured length |
| `descriptions` | Validates aint descriptions |
| `epic-files` | Checks directory-form aint structure |
| `sync` | Checks `.aint/` is clean and on `aint-sync` branch |

### Cleanup checks (only run when selected via `--only`)

| Check | What it does |
|-------|--------------|
| `clean-worktrees` | Finds git worktrees without corresponding aints |
| `clean-branches` | Finds local branches without corresponding aints |
| `clean-tmux` | Finds tmux sessions for closed/missing aints |
| `clean-aints` | Finds closed aints that can be archived further |

Cleanup checks don't run by default — they require `--only` or a shorthand
like `git aint cleanup` (which runs `doctor --fix --only clean-worktrees,clean-branches,clean-tmux,clean-aints`).

## Scoped checks

When targeting a specific aint, cleanup checks run in report-only mode (no fixes)
to avoid modifying resources belonging to other aints:

```
git aint doctor ab12c            # validate just this aint
git aint doctor ab12c --fix      # fix issues for this aint
```

## Fix behavior

With `--fix`:

- **Sync check:** Runs a full sync (pull, commit, push) for uncommitted changes.
- **Cleanup checks:** Removes stale worktrees, deletes gone branches, kills orphaned
  tmux sessions, archives closed aints.
- **Blocked items:** Some issues require manual intervention and are marked as BLOCKED
  in the output (e.g., worktrees with uncommitted changes).

## Examples

```
$ git aint doctor
aint-worktree  ok
parsing        ok
references     ok
cycles         ok
sync           fail
  2 uncommitted change(s) in .aint/

$ git aint doctor --fix
sync           fixed
  2 uncommitted change(s) in .aint/ (fixed: synced 2)

$ git aint doctor --only clean-worktrees,clean-branches --fix
clean-worktrees  fixed
  ab12c.fix-auth: aint is merged (removed)
clean-branches   ok
```
