#!/usr/bin/env bash
set -eu

case "${1:-}" in
  elegant)
    AINT_DIR="$(git rev-parse --show-toplevel)/.aint"
    FILE="$AINT_DIR/scripts/md/really-elegant.md"
    if [ ! -f "$FILE" ]; then
      echo "error: file not found: $FILE" >&2
      echo "  hint: run 'git aint init' to set up defaults" >&2
      exit 1
    fi
    cat "$FILE"
    ;;
  tracking)
    shift; exec git aint doctor --only sync "$@"
    ;;
  organized)
    shift; exec git aint doctor --only descriptions,epic-files "$@"
    ;;
  hygienic)
    shift; exec git aint doctor --only clean-worktrees,clean-branches,clean-tmux,clean-aints "$@"
    ;;
  configured)
    shift; exec git aint init "$@"
    ;;
  helping)
    shift; exec git aint list --stats "$@"
    ;;
  working)
    shift; exec git aint doctor "$@"
    ;;
  "")
    exec git aint doctor "$@"
    ;;
  *)
    echo "error: unknown check '$1'" >&2
    echo "  hint: try 'git aint doctor' instead" >&2
    exit 1
    ;;
esac
