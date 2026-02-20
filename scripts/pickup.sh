#!/bin/sh
ref="$1"

# 1. reject closed tasks
status=$(git aint get "$ref" --format "{status}") || exit 1
if [ "$status" = done ] || [ "$status" = wont_do ]; then
  echo "error: [$ref] is already $status" >&2; exit 1
fi

# 2. resolve branch + worktree dir + task id
branch=$(git aint get "$ref" --format "{config:branch-pattern}") || exit 1
wt_dir=$(git aint get "$ref" --format "{config:worktree-dir}") || exit 1
task_id=$(git aint get "$ref" --format "{task}") || exit 1

# 3. create worktree idempotently
if [ ! -d "$wt_dir/$branch" ]; then
  git worktree add "$wt_dir/$branch" -b "$branch" 2>/dev/null ||
  git worktree add "$wt_dir/$branch" "$branch" || exit 1
fi

# 4. create tmux session idempotently
if ! tmux has-session -t "$task_id" 2>/dev/null; then
  tmux new-session -d -s "$task_id" -c "$wt_dir/$branch" || exit 1
fi

# 5. set up tmux session logging (best-effort)
aint_path=$(git aint get "$ref" --format "{path}") &&
epic_dir=$(dirname "$aint_path") &&
logdir="$(pwd)/.aint/aints/$epic_dir/.tmux-logs/$task_id" &&
mkdir -p "$logdir" &&
ts=$(date -u +%Y-%m-%dT%H-%M-%S) &&
tmux pipe-pane -o -t "$task_id" "cat >> $logdir/$ts.w0p0.log.ansi" &&
tmux set-hook -t "$task_id" after-new-window "pipe-pane -o \"cat >> $logdir/$ts.w#{window_index}p0.log.ansi\"" &&
tmux set-hook -t "$task_id" after-split-window "pipe-pane -o \"cat >> $logdir/$ts.w#{window_index}p#{pane_index}.log.ansi\"" || true

# 6. update aint
git aint update "$ref" --status in_progress --add-tag "worktree:$branch" || exit 1

# 7. summary
echo ""
echo "Picked up [$ref] in $wt_dir/$branch"
echo "  attach:  $ tmux attach -t $task_id"
echo "  exec:    $ git aint exec $ref -- git status"
echo "  finish:  $ git aint update $ref --status done"
echo "  cleanup: $ git aint cleanup $ref"
