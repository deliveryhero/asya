#!/bin/sh
# Description: Manage tmux sessions for aints
subcmd="$1"; shift
ref="$1"; shift 2>/dev/null

# Parse remaining flags
fix=false
for arg in "$@"; do
  case "$arg" in
    --fix) fix=true ;;
  esac
done

repo_root=$(git rev-parse --show-toplevel) || exit 1

if [ "$subcmd" = "attach" ]; then
  [ -z "$ref" ] && { echo "usage: git aint tmux attach <ref>" >&2; exit 1; }

  tmux_name=$(git aint get "$ref" --format "{config:tmux-session-pattern}") || exit 1

  # Determine working directory: worktree if exists, else repo root
  wt_pattern=$(git aint get "$ref" --format "{config:worktree-pattern}") || exit 1
  wt_dir="$repo_root/$(git config aint.worktree-dir 2>/dev/null || echo '.worktrees')/$wt_pattern"
  if [ -d "$wt_dir" ]; then
    work_dir="$wt_dir"
  else
    work_dir="$repo_root"
  fi

  # Create session if needed (exact match with =)
  if ! tmux has-session -t "=$tmux_name" 2>/dev/null; then
    tmux new-session -d -s "$tmux_name" -c "$work_dir" || exit 1
    echo "Created session $tmux_name"
  fi

  # Attach or switch
  if [ -n "$TMUX" ]; then
    tmux switch-client -t "=$tmux_name"
  else
    tmux attach-session -t "=$tmux_name"
  fi

elif [ "$subcmd" = "list" ] || [ "$subcmd" = "ls" ]; then
  sessions=$(tmux list-sessions -F "#{session_name}" 2>/dev/null) || exit 0
  [ -z "$sessions" ] && exit 0

  printf "%-30s  %-10s  %s\n" "SESSION" "STATUS" "TITLE"
  while IFS= read -r name; do
    # Extract aint ID: first segment before "."
    aint_id=$(printf '%s' "$name" | sed 's|\..*||')
    info=$(git aint get "$aint_id" --format "{status}\t{title}" 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$info" ]; then
      status=$(printf '%s' "$info" | cut -f1)
      title=$(printf '%s' "$info" | cut -f2)
    else
      status="-"
      title="(no matching aint)"
    fi
    printf "%-30s  %-10s  %s\n" "$name" "$status" "$title"
  done <<EOF
$sessions
EOF

elif [ "$subcmd" = "kill" ]; then
  [ -z "$ref" ] && { echo "usage: git aint tmux kill <ref>" >&2; exit 1; }
  tmux_name=$(git aint get "$ref" --format "{config:tmux-session-pattern}") || exit 1
  if tmux kill-session -t "=$tmux_name" 2>/dev/null; then
    echo "Killed session $tmux_name"
  else
    echo "No session found: $tmux_name" >&2; exit 1
  fi

elif [ "$subcmd" = "cleanup" ]; then
  sessions=$(tmux list-sessions -F "#{session_name}" 2>/dev/null) || exit 0
  [ -z "$sessions" ] && { echo "No tmux sessions found."; exit 0; }

  found=false
  while IFS= read -r name; do
    aint_id=$(printf '%s' "$name" | sed 's|\..*||')
    info=$(git aint get "$aint_id" --format "{status}" 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "$info" ]; then
      reason="no matching aint"
    elif [ "$info" = "merged" ] || [ "$info" = "rejected" ]; then
      reason="aint is $info"
    else
      continue  # aint is active, skip
    fi

    if ! $found; then
      echo "Orphaned tmux sessions:"
      found=true
    fi

    if $fix; then
      if tmux kill-session -t "=$name" 2>/dev/null; then
        echo "  killed: $name ($reason)"
      else
        echo "  failed: $name ($reason)" >&2
      fi
    else
      echo "  $name ($reason)"
    fi
  done <<EOF
$sessions
EOF

  if ! $found; then
    echo "No orphaned sessions found."
  elif ! $fix; then
    echo ""
    echo "Run with --fix to kill these sessions."
  fi

else
  echo "usage: git aint tmux <attach|list|kill|cleanup> [ref] [--fix]" >&2
  exit 1
fi
