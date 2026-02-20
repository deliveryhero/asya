#!/usr/bin/env bash
set -euo pipefail

AINT_DIR="$(git rev-parse --show-toplevel)/.aint"
MD_DIR="$AINT_DIR/scripts/md"

if [ ! -d "$MD_DIR" ]; then
    echo "error: directory not found: $MD_DIR" >&2
    echo "  hint: run 'git aint init' to set up defaults" >&2
    exit 1
fi

# List available just-* topics
list_topics() {
    for f in "$MD_DIR"/just-*.md; do
        [ -f "$f" ] || continue
        _base="$(basename "$f" .md)"
        _base="${_base#just-}"
        echo "$_base" | tr '-' ' '
    done
}

if [ $# -eq 0 ]; then
    echo "available topics:"
    echo
    list_topics | while IFS= read -r topic; do
        echo "  git aint just $topic"
    done
    echo
    echo "edit: $MD_DIR/just-*.md"
    exit 0
fi

# Join args, lowercase, replace spaces with hyphens for filename lookup
QUERY="$(echo "$*" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"
FILE="$MD_DIR/just-${QUERY}.md"

if [ ! -f "$FILE" ]; then
    echo "error: topic '$*' not found" >&2
    echo "  available:" >&2
    list_topics | sed 's/^/    /' >&2
    echo "  hint: create $MD_DIR/just-${QUERY}.md to add it" >&2
    exit 1
fi

cat "$FILE"
