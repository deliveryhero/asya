# Troubleshooting

git-aint is plain files, YAML, and git. When the CLI can't help, fall back to
standard file operations and git commands.

## `.aint/` worktree is on the wrong branch

**Symptom:** `git aint sync` errors with:

```
.aint/ worktree is on branch 'rebase-...' expected 'aint-sync'
```

**Cause:** A previous sync had a rebase conflict that left a detached branch.

**Fix:**

```bash
cd .aint
git checkout aint-sync
git merge rebase-...        # or just drop it
git branch -d rebase-...
git push
```

Or nuke and re-init (safe — remote has everything):

```bash
rm -rf .aint
git worktree prune
git aint init
```

## Merge conflicts in `.aint/`

**Cause:** Two people edited the same aint file, or `auto_state.md` diverged.

**Quick fix — keep your local version:**

```bash
cd .aint
git checkout --theirs .     # keep remote version
# or
git checkout --ours .       # keep local version
git add -A
git rebase --continue
git push
```

**For `auto_state.md` specifically:** This file is regenerated on every sync.
Just discard it and re-sync:

```bash
cd .aint
git checkout HEAD -- auto_state.md
git aint sync --summarize
```

**Why this is safe:** Aint files are markdown with YAML frontmatter. The
"source of truth" is the file itself — there's no separate database. If a
conflict garbles frontmatter, fix it by hand (it's just YAML) and sync.

## `git aint init` fails

**"not inside a git repository"** — Run `git init` first.

**"failed to run git"** — git is not installed or not in PATH.

**Push fails on fresh init** — No remote configured, or offline. This is fine.
Aints work locally. Push later with:

```bash
git -C .aint push -u origin aint-sync
```

**Reinit after clone** — `git aint init` fetches `aint-sync` from remote
automatically. If it doesn't find it, check `git branch -r` for the branch.

## "aint not found" / wrong ID

**Symptom:** `git aint get ab12c` says not found, but you know it exists.

**Causes:**
- Typo in the ID — the CLI suggests similar IDs if it can find one.
- Aint is closed (in `archive/`) and you're filtering to active only.
  Try `git aint get ab12c --status-group all`.
- `.aint/` is out of date. Run `git aint sync` to pull.

**Manual lookup:**

```bash
find .aint -name "*ab12c*"
```

## "no worktree tag" on exec

**Symptom:** `git aint exec ab12c -- ...` errors with "no worktree tag."

**Cause:** The aint doesn't have a worktree yet.

**Fix:** Run `git aint pickup ab12c` first, or add the tag manually:

```bash
git aint set ab12c --add-tag "worktree:.worktrees/ab12c.fix-auth"
```

## Push keeps failing

**Symptom:** Sync or set commands fail on push after retries.

**Cause:** Remote has diverged, network issues, or auth problems.

**Manual resolution:**

```bash
cd .aint
git status              # check for uncommitted changes
git log --oneline -5    # see recent commits
git pull --rebase       # try pulling manually
git push                # try pushing manually
```

If completely stuck:

```bash
cd .aint
git fetch origin aint-sync
git reset --hard origin/aint-sync    # WARNING: discards local changes
git aint sync
```

## Corrupt or unparseable frontmatter

**Symptom:** `git aint get` or `doctor` reports parsing errors.

**Fix:** Open the file and fix the YAML. Common issues:
- Missing `---` delimiters
- Unquoted special characters in title (`:`, `[`, `#`)
- Invalid status value
- Priority out of range (must be 0-4)

Minimal valid frontmatter:

```yaml
---
title: My aint
---
```

`status` defaults to `open`, `priority` defaults to `2`. Everything else is optional.

## Accidentally deleted an aint

**Recovery:** The deletion was committed to `aint-sync`. Recover from git history:

```bash
cd .aint
git log --diff-filter=D --name-only    # find the commit
git checkout <commit>^ -- path/to/aint.fix-auth.ab12c.md
git aint sync
```

## Stale worktrees / branches / tmux sessions

**Symptom:** Orphaned resources from closed aints.

**Fix:**

```bash
git aint cleanup          # removes stale worktrees, branches, tmux sessions
# or step by step:
git aint doctor --only clean-worktrees --fix
git aint doctor --only clean-branches --fix
git aint doctor --only clean-tmux --fix
```

## Dependency cycle

**Symptom:** `git aint set --add-dep` fails with "would create a cycle."

**Fix:** The error shows the cycle path (e.g., `A -> B -> C -> A`).
Remove one of the dependencies to break the cycle:

```bash
git aint set <id> --rm-dep <blocking-id>
```

## Falling back to raw file operations

When the CLI doesn't cover your use case, edit files directly:

```bash
# Create an aint by hand
cat > .aint/active/aint.my-task.ab12c.md << 'EOF'
---
title: My task
status: open
priority: 2
---

Description here.
EOF

# Bulk status update
cd .aint/active
for f in aint.*.md; do
  sed -i 's/status: open/status: working/' "$f"
done

# Move an aint to archive manually
mv .aint/active/aint.done.ab12c.md .aint/archive/

# Commit everything
git aint sync
```

The only rules:
1. Aint filenames must match `aint.{slug}.{id}.md` (or `aint.{slug}.{id}/aint.md` for directories)
2. Frontmatter must have at least `title:`
3. Run `git aint sync` after manual edits to commit and push
