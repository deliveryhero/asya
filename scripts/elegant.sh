#!/usr/bin/env sh
set -eu

AINT_DIR="$(git rev-parse --show-toplevel)/.aint"
FILE="$AINT_DIR/scripts/md/really-elegant.md"

if [ ! -f "$FILE" ]; then
    echo "error: file not found: $FILE" >&2
    echo "  hint: run 'git aint init' to set up defaults" >&2
    exit 1
fi

cat "$FILE"
