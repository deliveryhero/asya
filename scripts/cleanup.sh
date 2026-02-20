#!/bin/sh
ref="$1"; shift

# 1. resolve worktree info
branch=$(git aint get "$ref" --format "{tag:worktree}") || exit 1
wt_dir=$(git aint get "$ref" --format "{config:worktree-dir}") || exit 1
task_id=$(git aint get "$ref" --format "{task}") || exit 1

# 2. check for uncommitted changes
status=$(git -C "$wt_dir/$branch" status --porcelain) || exit 1
if [ -n "$status" ]; then
  echo "error: worktree has uncommitted changes — commit or stash first" >&2
  exit 1
fi

# 3. check branch is merged into main
main=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')
[ -n "$main" ] || main="main"
if ! git merge-base --is-ancestor "$branch" "$main"; then
  echo "error: $branch is not merged into $main" >&2
  exit 1
fi

# 4. remove worktree + delete branch
git worktree remove "$wt_dir/$branch" "$@" || exit 1
git branch -d "$branch" 2>/dev/null

# 5. remove worktree tag
git aint update "$ref" --rm-tag "worktree:$branch" || exit 1

# 6. kill tmux session
tmux kill-session -t "$task_id" 2>/dev/null

echo "Cleaned up [$ref]: worktree removed, branch $branch deleted"
