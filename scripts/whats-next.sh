#!/bin/sh
# whats-next: show unblocked tasks ready to work on
#
# Usage:
#   git aint whats-next                    # human: open + deps clear
#   git aint whats-next --for agent        # agent: open + deps clear
#   git aint whats-next --for human --epic init  # scoped to epic

FOR="human"
PASSTHROUGH=""

# Parse --for flag, collect remaining args
while [ $# -gt 0 ]; do
  case "$1" in
    --for)
      shift
      FOR="$1"
      shift
      ;;
    --for=*)
      FOR="${1#--for=}"
      shift
      ;;
    *)
      PASSTHROUGH="$PASSTHROUGH $1"
      shift
      ;;
  esac
done

case "$FOR" in
  human)
    STATUS="open"
    ;;
  agent)
    STATUS="open"
    ;;
  *)
    echo "error: --for must be 'human' or 'agent', got '$FOR'" >&2
    exit 1
    ;;
esac

# shellcheck disable=SC2086
exec git aint list --deps clear --status "$STATUS" $PASSTHROUGH
