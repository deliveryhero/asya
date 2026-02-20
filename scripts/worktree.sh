#!/bin/sh
subcmd="$1"; shift

if [ "$subcmd" = "list" ] || [ "$subcmd" = "ls" ]; then
  git aint list --tag worktree --status all --columns tag:worktree "$@"
elif [ "$subcmd" = "remove" ] || [ "$subcmd" = "rm" ]; then
  ref="$1"; shift
  branch=$(git aint get "$ref" --format "{tag:worktree}") || exit 1
  wt_dir=$(git aint get "$ref" --format "{config:worktree-dir}") || exit 1
  git worktree remove "$wt_dir/$branch" "$@" || exit 1
  git aint update "$ref" --rm-tag "worktree:$branch" || exit 1
  echo "Removed worktree for [$ref]"
else
  echo "usage: git aint worktree <list|remove> [ref]" >&2
  exit 1
fi
