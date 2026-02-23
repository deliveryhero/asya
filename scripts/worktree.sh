#!/bin/sh
subcmd="$1"; shift

if [ "$subcmd" = "list" ] || [ "$subcmd" = "ls" ]; then
  # Query live git worktrees (not the aint DB)
  wt_dir=$(git config aint.worktree-dir 2>/dev/null || echo ".worktrees")
  repo_root=$(git rev-parse --show-toplevel) || exit 1
  wt_base="$repo_root/$wt_dir"
  [ -d "$wt_base" ] || exit 0

  found=false
  git worktree list --porcelain | awk '
    /^worktree / { path = substr($0, 10) }
    /^branch /   { branch = substr($0, 8); sub("refs/heads/", "", branch) }
    /^detached/  { branch = "(detached)" }
    /^$/         { if (path != "") print path "\t" branch; path=""; branch="" }
    END          { if (path != "") print path "\t" branch }
  ' | while IFS='	' read -r path branch; do
    # Filter to managed worktrees
    case "$path" in
      "$wt_base"/*)
        if ! $found; then
          printf "%-40s  %-10s  %s\n" "BRANCH" "STATUS" "TITLE"
          found=true
        fi

        # Extract task ID from branch: "epic/task.slug" -> "task" (part before first dot)
        task_part=$(printf '%s' "$branch" | sed 's|.*/||; s|\..*||')
        info=$(git aint get "$task_part" --format "{status}	{title}" 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "$info" ]; then
          status=$(printf '%s' "$info" | cut -f1)
          title=$(printf '%s' "$info" | cut -f2)
        else
          status="-"
          title="(no matching aint)"
        fi
        printf "%-40s  %-10s  %s\n" "$branch" "$status" "$title"
        ;;
    esac
  done
elif [ "$subcmd" = "remove" ] || [ "$subcmd" = "rm" ]; then
  ref="$1"; shift
  wt_path=$(git aint get "$ref" --format "{tag:worktree}") || exit 1
  branch=$(git aint get "$ref" --format "{tag:branch}") || exit 1
  git worktree remove "$wt_path" "$@" || exit 1
  git aint update "$ref" --rm-tag "worktree:$wt_path" --rm-tag "branch:$branch" || exit 1
  echo "Removed worktree for [$ref]"
else
  echo "usage: git aint worktree <list|remove> [ref]" >&2
  exit 1
fi
