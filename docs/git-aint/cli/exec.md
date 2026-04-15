# `git aint exec`

Run a command inside an aint's worktree with template expansion.

## Usage

```
git aint exec <ref> -- <command...>
```

## What it does

1. Resolves the aint's `worktree` tag to find the worktree directory.
2. Expands `{placeholder}` templates in each command argument.
3. Executes the command in the worktree directory.
4. Propagates the command's exit code.

## Requirements

The aint must have a `worktree` tag (set by `git aint pickup`). If not,
you'll get an error suggesting you run pickup first.

The worktree directory must exist on disk. If it's been removed, run pickup again.

## Template placeholders

| Placeholder | Value |
|-------------|-------|
| `{id}` | Aint ID (e.g., `ab12c`) |
| `{slug}` | Aint slug (e.g., `fix-auth`) |
| `{dir}` | Parent directory ID |
| `{dir_slug}` | Parent directory slug |
| `{title}` | Aint title |
| `{status}` | Current status |
| `{priority}` | Priority (0-4) |
| `{assignee}` | Assignee name |
| `{path}` | Full file path |
| `{ref}` | Full reference |
| `{tag:KEY}` | Value of a tag (e.g., `{tag:worktree}`) |
| `{config:KEY}` | Value of git config `aint.KEY` |

Backward-compatible aliases: `{epic}` = `{dir}`, `{epic_slug}` = `{dir_slug}`,
`{task}` = `{id}`, `{task_slug}` = `{slug}`.

## Examples

```
$ git aint exec ab12c -- git status
# runs `git status` in the ab12c worktree

$ git aint exec ab12c -- npm test
# runs `npm test` in the worktree

$ git aint exec ab12c -- bash -c "echo {title}: {status}"
Fix auth redirect: working
```
