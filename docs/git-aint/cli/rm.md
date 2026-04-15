# `git aint rm`

Remove an aint or a file within an aint directory.

## Usage

```
git aint rm <ref> [--file <filename>]
```

## Removing an entire aint

```
git aint rm ab12c
```

- **File-form:** Deletes the `.md` file.
- **Dir-form:** Recursively deletes the entire directory and all its children.

The deletion is committed and pushed automatically.

## Removing a file from a directory-form aint

```
git aint rm ab12c --file rfc.md
```

Removes only the named file from the aint's directory, preserving the aint itself
and all other files. Errors if the aint is file-form (not a directory container).

## Flags

| Flag | Effect |
|------|--------|
| `--file <FILENAME>` | Remove a specific file instead of the entire aint |
| `--no-commit` | Skip auto-commit (implies `--no-push`) |
| `--no-push` | Skip auto-push |
| `--no-pull` | Skip auto-pull |
| `-o\|--output json\|yaml\|table` | Output format |

## Recovery

There is no soft-delete or trash mechanism. Files are deleted from disk and the
deletion is committed. Git history preserves them — use `git log` and `git checkout`
to recover if needed.

## Examples

```
$ git aint rm ab12c
removed /path/to/.aint/active/aint.fix-auth.ab12c.md

$ git aint rm ef56g --file rfc.md
removed /path/to/.aint/active/aint.gateway.ef56g/rfc.md
```
