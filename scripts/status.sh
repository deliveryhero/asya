#!/bin/sh
# Description: Show what's active: working/pushed aints with worktrees, branches, and PRs
exec git aint get --status working pushed --columns "tag:worktree" "tag:branch" "tag:pr"
