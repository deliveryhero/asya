#!/bin/sh
subcmd="$1"; shift
ref="$1"; shift 2>/dev/null

if [ "$subcmd" = "list" ] || [ "$subcmd" = "ls" ]; then
  # Query live tmux sessions (not the aint DB)
  sessions=$(tmux list-sessions -F "#{session_name}" 2>/dev/null) || exit 0
  [ -z "$sessions" ] && exit 0

  found=false
  echo "$sessions" | while IFS= read -r name; do
    # Only consider sessions that look like aint IDs (3-10 lowercase alphanumeric)
    printf '%s' "$name" | grep -qE '^[a-z0-9]{3,10}$' || continue

    if ! $found; then
      printf "%-10s  %-10s  %s\n" "SESSION" "STATUS" "TITLE"
      found=true
    fi

    info=$(git aint get "$name" --format "{status}	{title}" 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$info" ]; then
      status=$(printf '%s' "$info" | cut -f1)
      title=$(printf '%s' "$info" | cut -f2)
    else
      status="-"
      title="(no matching aint)"
    fi
    printf "%-10s  %-10s  %s\n" "$name" "$status" "$title"
  done

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
    logdir="$(pwd)/.aint/epics/$epic_dir/.tmux-logs/$task_id" &&
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
