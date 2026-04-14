#!/bin/sh
# Description: Reject an aint with optional reason
ref="$1"; shift
[ -z "$ref" ] && { echo "usage: git aint reject <ref> [--reason \"...\"]" >&2; exit 1; }

# Parse --reason flag
reason=""
while [ $# -gt 0 ]; do
  case "$1" in
    --reason) shift; reason="$1"; shift ;;
    *) shift ;;
  esac
done

# Update status
if [ -n "$reason" ]; then
  git aint set "$ref" --status rejected --reason "$reason" || exit 1
else
  git aint set "$ref" --status rejected || exit 1
fi

echo "Rejected [$ref]"
