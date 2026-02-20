#!/bin/sh
subcmd="$1"; shift
ref="$1"; shift 2>/dev/null

if [ "$subcmd" = "list" ] || [ "$subcmd" = "ls" ]; then
  git aint list --tag worktree --status all --columns task "$@"

elif [ "$subcmd" = "kill" ]; then
  task_id=$(git aint get "$ref" --format "{task}") || exit 1
  tmux kill-session -t "$task_id" 2>/dev/null &&
  echo "Killed session $task_id"

elif [ "$subcmd" = "attach" ]; then
  task_id=$(git aint get "$ref" --format "{task}") || exit 1
  if tmux has-session -t "$task_id" 2>/dev/null; then
    tmux attach -t "$task_id"
  else
    # recreate session in worktree with logging
    branch=$(git aint get "$ref" --format "{tag:worktree}") || exit 1
    wt_dir=$(git aint get "$ref" --format "{config:worktree-dir}") || exit 1
    tmux new-session -d -s "$task_id" -c "$wt_dir/$branch" || exit 1
    aint_path=$(git aint get "$ref" --format "{path}") &&
    epic_dir=$(dirname "$aint_path") &&
    logdir="$(pwd)/.aint/aints/$epic_dir/.tmux-logs/$task_id" &&
    mkdir -p "$logdir" &&
    ts=$(date -u +%Y-%m-%dT%H-%M-%S) &&
    tmux pipe-pane -o -t "$task_id" "cat >> $logdir/$ts.w0p0.log.ansi" &&
    tmux set-hook -t "$task_id" after-new-window "pipe-pane -o \"cat >> $logdir/$ts.w#{window_index}p0.log.ansi\"" &&
    tmux set-hook -t "$task_id" after-split-window "pipe-pane -o \"cat >> $logdir/$ts.w#{window_index}p#{pane_index}.log.ansi\"" || true
    tmux attach -t "$task_id"
  fi

else
  echo "usage: git aint tmux <list|attach|kill> [ref]" >&2
  exit 1
fi
