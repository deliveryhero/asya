#!/bin/sh
ref="$1"
[ -z "$ref" ] && { echo "usage: git aint pickup <ref>" >&2; exit 1; }

# 1. reject closed tasks
status=$(git aint get "$ref" --format "{status}") || exit 1
if [ "$status" = merged ] || [ "$status" = rejected ]; then
  echo "error: [$ref] is already $status" >&2; exit 1
fi
if [ "$status" = open ]; then
  echo "error: [$ref] is open — peep it first: git aint peep $ref" >&2; exit 1
fi

# 2. resolve branch + worktree path
branch=$(git aint get "$ref" --format "{config:branch-pattern}") || exit 1
wt_pattern=$(git aint get "$ref" --format "{config:worktree-pattern}") || exit 1
repo_root=$(git rev-parse --show-toplevel) || exit 1
wt_rel="$(git config aint.worktree-dir 2>/dev/null || echo '.worktrees')/$wt_pattern"
wt_dir="$repo_root/$wt_rel"

# 3. create worktree idempotently
if [ ! -d "$wt_dir" ]; then
  git worktree add "$wt_dir" -b "$branch" 2>/dev/null ||
  git worktree add "$wt_dir" "$branch" || exit 1
fi

# 4. update aint
git aint update "$ref" --status active --add-tag "worktree:$wt_rel" --add-tag "branch:$branch" || exit 1

# 5. summary
echo ""
echo "Picked up [$ref] in $wt_dir"
echo "  tmux:    $ git aint tmux attach $ref"
echo "  exec:    $ git aint exec $ref -- git status"
echo "  finish:  $ git aint update $ref --status merged"
echo "  cleanup: $ git aint cleanup $ref"
