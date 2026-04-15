# `git aint set`

Update aint fields. Supports batch updates on multiple aints at once.

## Usage

```
git aint set <ref...> [options]
```

## What it does

1. Resolves each aint reference.
2. Applies field updates to the in-memory aint.
3. Writes the updated frontmatter back to disk.
4. Moves files between `active/` and `archive/` as needed.
5. Commits and pushes all changes in one batch.

## Flags

| Flag | Effect |
|------|--------|
| `--status <STATUS>` | Set status: open, working, pushed, merged, rejected |
| `--priority <0-4>` | Set priority |
| `--assignee <NAME>` | Set assignee |
| `--title <TEXT>` | Change title |
| `--reason <TEXT>` | Set reason (e.g. why status changed) |
| `--add-tag <KEY:VAL...>` | Add tags (duplicate-safe, no-op if already present) |
| `--rm-tag <KEY:VAL...>` | Remove tags (no-op if not present) |
| `--add-dep <REF...>` | Add dependencies (with cycle detection) |
| `--rm-dep <REF...>` | Remove dependencies |
| `--slug <TEXT>` | Rename (changes file or directory name) |
| `--in <DIR_ID>` | Move to a different parent directory (file-form only) |
| `--editor[=CMD]` | Open in editor after applying field changes |
| `--force` | Force close directory with open children |
| `--no-commit` | Skip auto-commit (implies `--no-push`) |
| `--no-push` | Skip auto-push |
| `--no-pull` | Skip auto-pull |
| `--output json\|yaml\|table` | Output format |

## File operations

### Status transitions and file movement

Active statuses (`open`, `working`, `pushed`) keep files in `active/`.
Closed statuses (`merged`, `rejected`) move files to `archive/`.

This happens automatically — setting status to `merged` moves the aint (file or
entire directory) from `active/` to `archive/`, and reopening moves it back.

For **child aints** (nested inside a parent directory), the same mirroring applies:
closing a child moves it to `archive/<parent-dir>/`.

### Slug rename

Renaming the slug renames the underlying file or directory:

```
git aint set ab12c --slug new-name
# file-form:  aint.old-name.ab12c.md  ->  aint.new-name.ab12c.md
# dir-form:   aint.old-name.ab12c/    ->  aint.new-name.ab12c/
```

### Moving between parents

```
git aint set ab12c --in ef56g   # move ab12c into ef56g's directory
```

Only works for file-form aints. Directory-form aints cannot be moved with `--in`.

## Automatic behaviors

### Auto-assignee

When status changes to `working` and no `--assignee` is given and the aint has
no assignee, it's automatically set to `git config user.name` (or `user.email`).

### Cycle detection

Adding dependencies triggers a full dependency graph cycle check. If the new
dependency would create a cycle, the operation fails with the cycle path shown.

### Close directory safety

Closing a directory-form aint (setting to merged/rejected) checks for open children.
If any exist, the operation fails with a list of open tasks. Use `--force` to
close anyway.

After closing the last child in a parent, a hint is printed suggesting you
review and close the parent.

## Editor integration

```
git aint set ab12c --editor          # use configured editor
git aint set ab12c --editor=vim      # use specific editor
```

Editor resolution order: `--editor=CMD` > `aint.editor` > `GIT_EDITOR` > `core.editor` > `VISUAL` > `EDITOR`

Friendly names are supported: `vscode` maps to `code --wait`, `subl` to `subl --wait`, etc.

The editor opens after field changes are applied, so you can combine flags with editing:

```
git aint set ab12c --status working --editor
```

## Examples

```
$ git aint set ab12c --status working
updated [ab12c] .aint/active/aint.fix-auth.ab12c.md

$ git aint set ab12c ef56g --priority 1
updated [ab12c] .aint/active/aint.fix-auth.ab12c.md
updated [ef56g] .aint/active/aint.add-api.ef56g.md

$ git aint set ab12c --status merged
updated [ab12c] .aint/archive/aint.fix-auth.ab12c.md
```
