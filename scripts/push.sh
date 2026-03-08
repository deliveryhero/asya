#!/bin/sh
# push-create-pr.sh — push branch to origin and create/update GitHub PR
set -e

# --- parse args ---
ref=""
title_override=""
description=""
while [ $# -gt 0 ]; do
  case "$1" in
    --title)   shift; title_override="$1" ;;
    --description) shift; description="$1" ;;
    -*)        echo "error: unknown flag $1" >&2; exit 1 ;;
    *)         [ -z "$ref" ] && ref="$1" ;;
  esac
  shift
done
[ -z "$ref" ] && { echo "usage: git aint push <ref> [--title <text>] [--description <text>]" >&2; exit 1; }

# --- check gh CLI ---
if ! command -v gh >/dev/null 2>&1; then
  echo "error: 'gh' CLI not found — install from https://cli.github.com" >&2
  exit 1
fi

# --- validate aint state ---
status=$(git aint get "$ref" --format "{status}") || exit 1
case "$status" in
  merged|rejected)
    echo "error: [$ref] is already $status" >&2; exit 1 ;;
esac

# --- resolve branch ---
branch=$(git aint get "$ref" --format "{config:branch-pattern}") || exit 1

# --- verify branch exists locally ---
git rev-parse --verify "refs/heads/$branch" >/dev/null 2>&1 || {
  echo "error: branch '$branch' does not exist locally — run 'git aint pickup $ref' first" >&2
  exit 1
}

# --- git push ---
git push -u origin "$branch" || exit 1

# --- check existing PR ---
pr_number=$(gh pr list --head "$branch" --json number --jq '.[0].number' 2>/dev/null) || true
if [ -n "$pr_number" ] && [ "$pr_number" != "null" ]; then
  pr_url=$(gh pr list --head "$branch" --json url --jq '.[0].url' 2>/dev/null) || true

  # ensure aint is tagged with pr:<number>
  existing_pr_tag=$(git aint get "$ref" --format "{tag:pr}" 2>/dev/null) || true
  if [ "$existing_pr_tag" != "$pr_number" ]; then
    git aint update "$ref" --add-tag "pr:$pr_number" || true
  fi

  echo "PR already exists: $pr_url"

  # set status to pushed if not already
  if [ "$status" != "pushed" ]; then
    git aint update "$ref" --status pushed || true
  fi

  exit 0
fi

# --- generate PR title ---
if [ -n "$title_override" ]; then
  pr_title="$title_override"
else
  pr_title=$(git aint get "$ref" --format "{config:pr-title-pattern}") || exit 1
fi

# --- generate PR body ---
repo_url=$(gh repo view --json url --jq '.url') || exit 1

# get aint metadata
aint_id=$(git aint get "$ref" --format "{id}") || exit 1
aint_title=$(git aint get "$ref" --format "{title}") || exit 1
aint_status=$(git aint get "$ref" --format "{status}") || exit 1
aint_path=$(git aint get "$ref" --format "{path}") || exit 1

body=""
if [ -n "$description" ]; then
  body="$description

"
fi

body="${body}## Aints

- [${aint_id}: ${aint_title}](${repo_url}/blob/aint-sync/.aint/epics/${aint_path}) (${aint_status})"

# add dependency bullets
deps=$(git aint get "$ref" -o json 2>/dev/null | grep -o '"dependencies":\[[^]]*\]' | grep -o '"[^"]*"' | tr -d '"') || true
for dep_id in $deps; do
  dep_title=$(git aint get "$dep_id" --format "{title}" 2>/dev/null) || continue
  dep_status=$(git aint get "$dep_id" --format "{status}" 2>/dev/null) || continue
  dep_path=$(git aint get "$dep_id" --format "{path}" 2>/dev/null) || continue
  body="${body}
- [${dep_id}: ${dep_title}](${repo_url}/blob/aint-sync/.aint/epics/${dep_path}) (${dep_status})"
done

# --- create PR ---
pr_output=$(gh pr create --head "$branch" --title "$pr_title" --body "$body" 2>&1) || {
  echo "error: gh pr create failed:" >&2
  echo "$pr_output" >&2
  exit 1
}

# extract PR number from URL (last path segment)
pr_number=$(echo "$pr_output" | grep -o '/pull/[0-9]*' | grep -o '[0-9]*' | tail -1)
if [ -z "$pr_number" ]; then
  echo "warning: could not extract PR number from: $pr_output" >&2
  echo "$pr_output"
  exit 0
fi

# --- tag aint with pr number ---
git aint update "$ref" --add-tag "pr:$pr_number" || true

# --- set status to pushed ---
if [ "$status" != "pushed" ]; then
  git aint update "$ref" --status pushed || true
fi

# --- summary ---
echo ""
echo "Created PR #${pr_number} for [$ref]"
echo "  url:   $pr_output"
echo "  aint:  git aint get $ref"
echo "  merge: git aint merge $ref"
